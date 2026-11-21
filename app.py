"""Web server for the talk-to-db app.  Run: .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765"""
import json
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

import auth
import config
import people
import schema

app = FastAPI(title="Talk to MIS DB")


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


DB_COOKIE = "ttd_db"


def _db(request: Request) -> str:
    """Which database this browser picked in the header (Local / Proxy)."""
    return config.db_key(request.cookies.get(DB_COOKIE))


class DbIn(BaseModel):
    key: str


@app.get("/api/databases")
def databases(request: Request):
    return {"current": _db(request),
            "options": [{"key": k, "label": d["label"]} for k, d in config.DATABASES.items()]}


@app.post("/api/database")
def set_database(body: DbIn, request: Request):
    if body.key not in config.DATABASES:
        raise HTTPException(400, "Unknown database.")
    people.audit(_client(request), "switch_db", {"db": body.key})
    resp = JSONResponse({"ok": True, "current": body.key})
    resp.set_cookie(DB_COOKIE, body.key, max_age=365 * 86400, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https")
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
    return {"auth_enabled": auth.enabled(), "user": user,
            "database": schema.CATALOG["database"], "table_count": len(schema.TABLES),
            "status_labels": people.STATUS_LABELS, "db": _db(request),
            "db_label": config.DATABASES[_db(request)]["label"]}


@app.get("/api/people/suggest")
def people_suggest(field: str, request: Request, prefix: str = ""):
    return people.suggest(field, prefix, dbk=_db(request))


NO_STORE = {"Cache-Control": "no-store"}   # pages show personal data: never serve them from the browser cache


@app.get("/")
def index():
    return FileResponse("static/index.html", headers=NO_STORE)


@app.get("/api/schema/search")
def schema_search(q: str):
    return schema.search_tables(q, limit=40)


@app.get("/api/schema/table/{name}")
def schema_table(name: str):
    return schema.describe_tables([name])


@app.get("/api/schema/modules")
def schema_modules():
    return {"database": schema.CATALOG["database"], "table_count": len(schema.TABLES),
            "modules": schema.CATALOG["modules"]}


@app.get("/api/people/search")
def people_search(q: str, request: Request):
    people.audit(_client(request), "search", {"q": people.redact_query(q), "db": _db(request)})
    return people.search(q, dbk=_db(request))


@app.get("/api/people/fields")
def people_fields():
    return people.SEARCH_FIELDS_HELP


@app.get("/api/people/{pid}")
def people_profile(pid: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "profile_reveal" if reveal else "profile", {"id": pid, "db": _db(request)})
    return people.profile(pid, reveal, dbk=_db(request))


@app.get("/api/people/{pid}/links")
def people_links(pid: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "links_reveal" if reveal else "links", {"id": pid, "db": _db(request)})
    return StreamingResponse((_sse(ev) for ev in people.stream_links(pid, reveal, dbk=_db(request))), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/people/{pid}/scan")
def people_scan(pid: str, table: str, request: Request, reveal: bool = False):
    people.audit(_client(request), "scan", {"id": pid, "table": table, "reveal": reveal, "db": _db(request)})
    return people.scan_one(pid, table, reveal, dbk=_db(request))


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
