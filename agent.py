"""Talk-to-DB agent: Claude explores the schema map, writes SQL, runs it read-only, and answers."""
import datetime
import decimal
import json
import os
import re
import time
from typing import Iterator

import anthropic
import sqlglot
from sqlglot import exp

from config import MAX_ROWS, MAX_ROWS_TO_MODEL, MODEL, QUERY_TIMEOUT_MS, ro_connect

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = json.load(open(os.path.join(HERE, "catalog.json")))
TABLES = CATALOG["tables"]
TABLES_LOWER = {k.lower(): k for k in TABLES}
KNOWLEDGE_PATH = os.path.join(HERE, "knowledge.md")
MAX_AGENT_TURNS = 25

# ---------------------------------------------------------------- schema tools

_WORD = re.compile(r"[a-z0-9]+")
_SYNONYMS = {
    "student": ["stu", "admn", "student"], "students": ["stu", "admn", "student"],
    "employee": ["emp", "employee", "faculty", "staff"], "staff": ["emp", "staff"],
    "faculty": ["faculty", "emp"], "attendance": ["absent", "attendance", "class", "engaged"],
    "marks": ["marks", "grade", "foil", "result"], "grade": ["grade", "marks", "foil", "cgpa"],
    "result": ["result", "foil", "marks", "grade"], "cgpa": ["cgpa", "gpa", "foil"],
    "fee": ["fee", "payment", "bank"], "fees": ["fee", "payment", "bank"],
    "salary": ["pay", "salary", "acc"], "leave": ["leave", "sleave"], "hostel": ["hs", "hostel", "hm"],
    "admission": ["adm", "admission"], "department": ["dept", "departments"], "course": ["course", "subject", "cbcs", "nep"],
    "subject": ["subject", "course", "sub"], "registration": ["reg", "registration", "form"],
    "phd": ["phd"], "mtech": ["mtech"], "mba": ["mba"], "medical": ["hc", "medicine", "patient"],
}


def _tokens(s: str) -> list[str]:
    return _WORD.findall(s.lower())


def search_tables(query: str, limit: int = 15) -> dict:
    words = set()
    for w in _tokens(query):
        words.add(w)
        words.update(_SYNONYMS.get(w, []))
    scored = []
    for name, t in TABLES.items():
        name_toks = set(_tokens(name.replace("_", " ")))
        col_toks = set()
        for c in t.get("columns", []):
            col_toks.update(_tokens(c["name"].replace("_", " ")))
        used = set()
        for u in t.get("used_by", []):
            used.update(_tokens(u.replace("_", " ")))
        score = 0.0
        for w in words:
            if w in name_toks:
                score += 5
            elif any(w in nt for nt in name_toks if len(w) >= 3):
                score += 2
            if w in col_toks:
                score += 1.5
            if w in used:
                score += 1
            if w in t.get("comment", "").lower():
                score += 2
        if score == 0:
            continue
        score += min(t.get("hub_score", 0), 30) / 6
        if t.get("is_backup_like"):
            score -= 6
        if t.get("approx_rows", 0) == 0 and t["type"] == "BASE TABLE":
            score -= 2
        scored.append((score, name))
    scored.sort(reverse=True)
    results = []
    for _, name in scored[: max(1, min(limit, 40))]:
        t = TABLES[name]
        results.append({
            "table": name,
            "approx_rows": t.get("approx_rows", 0),
            "type": "VIEW" if t["type"] == "VIEW" else "TABLE",
            "backup_like": t.get("is_backup_like", False),
            "columns": [c["name"] for c in t.get("columns", [])][:20],
            "used_by_code": t.get("used_by", [])[:5],
        })
    return {"matches": results}


def describe_tables(tables: list[str]) -> dict:
    out, missing = {}, []
    for raw in tables[:12]:
        name = TABLES_LOWER.get(raw.lower().strip("` "))
        if not name:
            missing.append(raw)
            continue
        t = TABLES[name]
        d = {
            "approx_rows": t.get("approx_rows", 0),
            "type": t["type"],
            "columns": t.get("columns", []),
            "joins": [j["on"] + (f"  (FK)" if j["source"] == "declared_fk" else f"  (used {j['uses']}x in code)")
                      for j in t.get("joins", [])],
            "used_by_code": t.get("used_by", []),
        }
        if t.get("is_backup_like"):
            d["warning"] = "Name looks like a backup/dated copy - prefer the live table unless asked."
        if t.get("comment"):
            d["comment"] = t["comment"]
        if t.get("view_definition"):
            d["view_definition"] = t["view_definition"][:1500]
        out[name] = d
    res = {"tables": out}
    if missing:
        res["not_found"] = missing
        res["hint"] = "Use search_tables to find the right name."
    return res


# ---------------------------------------------------------------- SQL tool

_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command,
              exp.Merge, exp.TruncateTable, exp.Into, exp.Lock, exp.Set)


class UnsafeQuery(ValueError):
    pass


def validate_sql(sql: str) -> str:
    """Allow exactly one read-only SELECT/WITH/UNION statement; add a LIMIT if missing."""
    try:
        stmts = [s for s in sqlglot.parse(sql, read="mysql") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQuery(f"SQL parse error: {str(e)[:300]}")
    if len(stmts) != 1:
        raise UnsafeQuery("Send exactly one statement.")
    stmt = stmts[0]
    if not isinstance(stmt, (exp.Select, exp.SetOperation)):  # WITH ... SELECT parses as Select
        raise UnsafeQuery("Only SELECT queries are allowed.")
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN):
            raise UnsafeQuery(f"Not allowed in read-only mode: {node.key.upper()}")
    if re.search(r"\b(into\s+(out|dump)file|load_file|sleep\s*\(|benchmark\s*\(|get_lock|for\s+update)\b", sql, re.I):
        raise UnsafeQuery("That function/clause is not allowed.")
    if isinstance(stmt, exp.Select) and not stmt.args.get("limit"):
        stmt = stmt.limit(MAX_ROWS)
    elif not isinstance(stmt, exp.Select) and not stmt.args.get("limit"):
        stmt = exp.select("*").from_(stmt.subquery("q")).limit(MAX_ROWS)
    return stmt.sql(dialect="mysql")


def _jsonable(v):
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    if isinstance(v, datetime.timedelta):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(v)} bytes>"
    return v


def run_sql(sql: str) -> dict:
    safe_sql = validate_sql(sql)
    started = time.time()
    conn = ro_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET SESSION max_execution_time = {int(QUERY_TIMEOUT_MS)}")
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute("START TRANSACTION READ ONLY")
            cur.execute(safe_sql)
            rows = cur.fetchmany(MAX_ROWS)
            cols = [d[0] for d in cur.description] if cur.description else []
            cur.execute("ROLLBACK")
    finally:
        conn.close()
    rows = [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    return {"sql": safe_sql, "columns": cols, "rows": rows, "row_count": len(rows),
            "truncated": len(rows) >= MAX_ROWS, "ms": int((time.time() - started) * 1000)}


def sql_result_for_model(res: dict) -> str:
    def clip(v):
        s = v if isinstance(v, (int, float)) or v is None else str(v)
        return s[:200] + "..." if isinstance(s, str) and len(s) > 200 else s
    rows = [{k: clip(v) for k, v in r.items()} for r in res["rows"][:MAX_ROWS_TO_MODEL]]
    payload = {"executed_sql": res["sql"], "columns": res["columns"], "row_count": res["row_count"],
               "rows": rows, "ms": res["ms"]}
    if res["row_count"] > MAX_ROWS_TO_MODEL:
        payload["note"] = (f"Showing first {MAX_ROWS_TO_MODEL} of {res['row_count']} rows "
                           f"(the user sees up to {MAX_ROWS}). Use COUNT/GROUP BY for totals.")
    elif res["truncated"]:
        payload["note"] = f"Result capped at {MAX_ROWS} rows."
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------- tool definitions

TOOLS = [
    {
        "name": "search_tables",
        "description": "Keyword search over the schema map (table names, column names, code module names). "
                       "Returns candidate tables with approximate row counts and their columns. Use first to find "
                       "where data lives; try several phrasings (e.g. 'attendance absent', 'grade cgpa foil').",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'student hostel room'"}},
            "required": ["query"], "additionalProperties": False},
        "strict": True,
        "eager_input_streaming": True,
    },
    {
        "name": "describe_tables",
        "description": "Full column list (types, keys), known join conditions (declared FKs and joins the "
                       "application code actually uses), and which code modules use each table. Call before "
                       "writing SQL against a table.",
        "input_schema": {"type": "object", "properties": {
            "tables": {"type": "array", "items": {"type": "string"}, "description": "Up to 12 table names"}},
            "required": ["tables"], "additionalProperties": False},
        "strict": True,
        "eager_input_streaming": True,
    },
    {
        "name": "run_sql",
        "description": "Run ONE read-only MySQL SELECT on the live database and get the rows back. A LIMIT is "
                       f"added if missing (max {MAX_ROWS} rows). Use it to explore too: SELECT DISTINCT on code/"
                       "status columns, COUNT(*), MIN/MAX of dates - check value formats before filtering.",
        "input_schema": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "A single SELECT statement (MySQL dialect)"},
            "purpose": {"type": "string", "description": "One short line shown to the user: what this query checks"}},
            "required": ["sql", "purpose"], "additionalProperties": False},
        "strict": True,
        "eager_input_streaming": True,
    },
]

TOOL_REQUIRED = {"search_tables": ["query"], "describe_tables": ["tables"], "run_sql": ["sql", "purpose"]}


def _module_overview() -> str:
    lines = []
    for m, s in CATALOG["modules"].items():
        if s["table_count"] < 3:
            continue
        label = f" - {s['label']}" if s["label"] else ""
        lines.append(f"{m}_ ({s['table_count']} tables){label}: {', '.join(s['core_tables'][:8])}")
    return "\n".join(lines)


def _hub_overview() -> str:
    hubs = sorted(TABLES.values(), key=lambda t: -t.get("hub_score", 0))[:30]
    out = []
    for t in hubs:
        cols = ", ".join(c["name"] for c in t.get("columns", [])[:14])
        out.append(f"{t['name']} (~{t.get('approx_rows', 0):,} rows): {cols}")
    return "\n".join(out)


def build_system_prompt() -> str:
    knowledge = open(KNOWLEDGE_PATH).read() if os.path.exists(KNOWLEDGE_PATH) else ""
    return f"""You answer questions about an institute's MIS (management information system) by querying its MySQL database `{CATALOG['database']}` ({len(TABLES)} tables). The people asking are institute staff; they want correct numbers and lists, not SQL lessons.

How to work:
- Find the right tables with search_tables and describe_tables before writing SQL. Many tables have near-duplicate names (dated copies, `_log`, `_desc`, `_freezed`, old CBCS vs current NEP curriculum). Prefer the live, well-connected table; say which one you used when there is a real choice.
- Use the join conditions from describe_tables - they come from how the application code itself joins tables. Don't invent join keys.
- Before filtering on codes, statuses, session years, or names, look at the real values (SELECT DISTINCT ... LIMIT 50). Formats vary (e.g. '2024-2025' vs '2024_25', 'monsoon' vs 'Monsoon').
- Row counts in the map are estimates; use COUNT(*) for exact numbers.
- If a question is ambiguous, pick the most sensible reading, run it, and state the assumption in one line. Ask a clarifying question only when no reasonable default exists.
- When a query errors, read the error, fix it, and retry.

Answering:
- Lead with the answer (the number, the list, the finding). Then one or two lines on how you got it: tables used and any assumption.
- The user sees every query's result table in the UI, so don't re-type large tables - summarise and point to the result.
- Show the final SQL in a ```sql block when it is non-trivial, so they can reuse it.
- For aggregate questions, return aggregates, not personal rows.

## Module map (prefix -> core tables)
{_module_overview()}

## Hub tables (most connected; with leading columns)
{_hub_overview()}

## Domain notes (maintained by the team in knowledge.md)
{knowledge}
"""


# ---------------------------------------------------------------- agent loop

client = anthropic.Anthropic()
SYSTEM_PROMPT = build_system_prompt()


def _validate_input(name: str, inp) -> str | None:
    if not isinstance(inp, dict):
        return "tool input was not an object"
    for key in TOOL_REQUIRED.get(name, []):
        if key not in inp:
            return f"missing required field '{key}' (input may have been truncated)"
    if name == "describe_tables" and not isinstance(inp.get("tables"), list):
        return "'tables' must be an array of strings"
    return None


def _execute(name: str, inp: dict) -> tuple[str, dict | None, bool]:
    """Returns (content_for_model, ui_payload, is_error)."""
    try:
        if name == "search_tables":
            res = search_tables(inp["query"])
            return json.dumps(res), {"kind": "search", "query": inp["query"],
                                     "tables": [m["table"] for m in res["matches"]]}, False
        if name == "describe_tables":
            res = describe_tables(inp["tables"])
            return json.dumps(res, default=str), {"kind": "describe", "tables": list(res["tables"])}, False
        if name == "run_sql":
            res = run_sql(inp["sql"])
            return sql_result_for_model(res), {"kind": "sql", "purpose": inp.get("purpose", ""), **res}, False
        return f"Unknown tool {name}", None, True
    except UnsafeQuery as e:
        return f"Rejected: {e}", {"kind": "sql_error", "sql": inp.get("sql", ""), "purpose": inp.get("purpose", ""),
                                   "error": str(e)}, True
    except Exception as e:  # DB errors go back to the model so it can fix the query
        msg = f"{type(e).__name__}: {e}"[:800]
        return f"Error: {msg}", {"kind": "sql_error" if name == "run_sql" else "tool_error",
                                 "sql": inp.get("sql", ""), "purpose": inp.get("purpose", ""), "error": msg}, True


def run_turn(messages: list, question: str) -> Iterator[dict]:
    """Append the question, run the tool loop, yield UI events. `messages` is mutated (append-only)."""
    messages.append({"role": "user", "content": question})
    for _ in range(MAX_AGENT_TURNS):
        yield {"type": "status", "text": "thinking"}
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            tools=TOOLS,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                    elif event.delta.type == "thinking_delta" and event.delta.thinking:
                        yield {"type": "thinking", "text": event.delta.thinking}
            response = stream.get_final_message()

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            yield {"type": "error", "text": "The model declined this request."}
            return
        if response.stop_reason == "max_tokens":
            yield {"type": "error", "text": "Response hit the length limit."}
            return
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            yield {"type": "done", "usage": {"input": response.usage.input_tokens,
                                             "output": response.usage.output_tokens,
                                             "cache_read": response.usage.cache_read_input_tokens or 0}}
            return

        results = []
        for tu in tool_uses:
            problem = _validate_input(tu.name, tu.input)
            if problem:
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"INVALID_INPUT: {problem}. Re-issue the call.", "is_error": True})
                continue
            yield {"type": "tool_start", "name": tu.name, "input": tu.input}
            content, ui, is_err = _execute(tu.name, tu.input)
            if ui:
                yield {"type": "tool_result", "name": tu.name, **ui}
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_err})
        messages.append({"role": "user", "content": results})
    yield {"type": "error", "text": f"Stopped after {MAX_AGENT_TURNS} steps without a final answer."}
