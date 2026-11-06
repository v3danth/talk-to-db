"""Web server for the talk-to-db app.  Run: .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765"""
import json
import threading
import uuid

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import agent
import people

app = FastAPI(title="Talk to MIS DB")
_sessions: dict[str, list] = {}
_locks: dict[str, threading.Lock] = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    question: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


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
    return request.headers.get("X-Forwarded-User") or (request.client.host if request.client else "?")


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"
