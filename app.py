"""Web server for the talk-to-db app.  Run: .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765"""
import json
import os
import threading
import uuid
from urllib.parse import quote

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

import agent
import auth
import people

app = FastAPI(title="Talk to MIS DB")
_sessions: dict[str, list] = {}
_locks: dict[str, threading.Lock] = {}


PUBLIC_PATHS = {"/login", "/api/login", "/api/status"}


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    """When sign-in is on (users.json exists), every page and API call needs a valid session."""
    if auth.enabled() and request.url.path not in PUBLIC_PATHS:
        user = auth.session_user(request.cookies.get(auth.COOKIE))
        if not user:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Sign in to continue."}, status_code=401)
            nxt = request.url.path  # the #fragment never reaches the server; login.html carries it over
            return RedirectResponse("/login?next=" + quote(nxt))
        request.state.user = user
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


class LoginIn(BaseModel):
    username: str
    password: str


@app.get("/login")
def login_page():
    return FileResponse("static/login.html", headers=NO_STORE)


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    wait = auth.rate_limited(ip)
    if wait:
        raise HTTPException(429, f"Too many failed attempts. Try again in {wait // 60 + 1} min.")
    token = auth.login(body.username.strip(), body.password, ip)
    people.audit(body.username.strip() + "@" + ip, "login" if token else "login_failed", {})
    if not token:
        raise HTTPException(401, "Wrong username or password.")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https")
    return resp


@app.post("/api/logout")
def logout(request: Request):
    people.audit(_client(request), "logout", {})
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/status")
def status(request: Request):
    user = auth.session_user(request.cookies.get(auth.COOKIE)) if auth.enabled() else None
    return {"auth_enabled": auth.enabled(), "user": user, "ai_ready": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "database": agent.CATALOG["database"], "table_count": len(agent.TABLES),
            "status_labels": people.STATUS_LABELS}


@app.get("/api/people/suggest")
def people_suggest(field: str, prefix: str = ""):
    return people.suggest(field, prefix)


class ChatIn(BaseModel):
    session_id: str | None = None
    question: str


NO_STORE = {"Cache-Control": "no-store"}   # pages show personal data: never serve them from the browser cache


@app.get("/")
def index():
    return FileResponse("static/index.html", headers=NO_STORE)


@app.post("/api/chat")
def chat(body: ChatIn):
    sid = body.session_id or uuid.uuid4().hex
    messages = _sessions.setdefault(sid, [])
    lock = _locks.setdefault(sid, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "This conversation is still answering the previous question.")

    def events():
        checkpoint = len(messages)
        try:
            yield _sse({"type": "session", "session_id": sid})
            for ev in agent.run_turn(messages, body.question.strip()):
                yield _sse(ev)
        except anthropic.APIConnectionError:
            del messages[checkpoint:]
            yield _sse({"type": "error", "text": "Could not reach the Claude API. Check your network."})
        except anthropic.AuthenticationError:
            del messages[checkpoint:]
            yield _sse({"type": "error", "text": "Claude API key missing or invalid. Set ANTHROPIC_API_KEY."})
        except anthropic.RateLimitError:
            del messages[checkpoint:]
            yield _sse({"type": "error", "text": "Rate limited by the Claude API. Wait a moment and retry."})
        except anthropic.APIStatusError as e:
            del messages[checkpoint:]
            yield _sse({"type": "error", "text": f"Claude API error {e.status_code}: {e.message}"[:500]})
        finally:
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/reset")
def reset(body: dict):
    _sessions.pop(body.get("session_id", ""), None)
    return {"ok": True}


@app.get("/api/schema/search")
def schema_search(q: str):
    return agent.search_tables(q, limit=40)


@app.get("/api/schema/table/{name}")
def schema_table(name: str):
    return agent.describe_tables([name])


@app.get("/api/schema/modules")
def schema_modules():
    return {"database": agent.CATALOG["database"], "table_count": len(agent.TABLES),
            "modules": agent.CATALOG["modules"]}


@app.get("/api/people/search")
def people_search(q: str, request: Request):
    people.audit(_client(request), "search", {"q": people.redact_query(q)})
    return people.search(q)


@app.get("/api/people/fields")
def people_fields():
    return people.SEARCH_FIELDS_HELP


@app.get("/api/people/{pid}")
def people_profile(pid: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "profile_reveal" if reveal else "profile", {"id": pid})
    return people.profile(pid, reveal)


@app.get("/api/people/{pid}/links")
def people_links(pid: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "links_reveal" if reveal else "links", {"id": pid})
    return StreamingResponse((_sse(ev) for ev in people.stream_links(pid, reveal)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/people/{pid}/scan")
def people_scan(pid: str, table: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "scan", {"id": pid, "table": table, "reveal": reveal})
    return people.scan_one(pid, table, reveal)


@app.get("/relationships")
def relationships_doc():
    return FileResponse("DB_RELATIONSHIPS.html")


def _client(request: Request) -> str:
    """Who to write in the audit log: the signed-in user when sign-in is on, else the client address."""
    ip = request.client.host if request.client else "?"
    user = getattr(request.state, "user", None)
    return f"{user['name']}@{ip}" if user else ip


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"
