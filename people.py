"""People lookup for the DB admin team: search students / faculty / staff and show everything linked to them.

No LLM involved - plain parameterised SQL on the read-only account.
"""
import concurrent.futures as cf
import datetime
import decimal
import json
import os
import re
import threading
import time

from config import QUERY_TIMEOUT_MS, db_key, ro_connect

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = json.load(open(os.path.join(HERE, "catalog.json")))
TABLES = CATALOG["tables"]
AUDIT_LOG = os.path.join(HERE, "logs", "people_access.log")
LARGE_UNINDEXED_ROWS = 150_000   # above this, an unindexed table is scanned only on demand
LINK_ROW_LIMIT = 50
LINK_WORKERS = 12
LINK_ORDER = {"user_login_attempts": "`time` DESC"}   # log tables: show the newest rows first

# Never shown, not even to admins.
HIDDEN_COL = re.compile(r"(passw|pwd$|^pwd|hash|otp|token|secret|salt$)", re.I)
# Shown masked unless the viewer clicks Reveal (which is audit-logged).
SENSITIVE_COL = re.compile(r"(aadh?a?a?r|pan_?no|pan_?card|passport|acc(ount)?_?no|bank_?acc|accno|ifsc|uan|pran)", re.I)

PERSON_TYPES = {
    "student": ("u.auth_id = 'stu'", "Student"),
    "faculty": ("e.auth_id = 'ft'", "Faculty"),
    "prof": ("e.auth_id = 'ft'", "Faculty"),
    "staff": ("e.auth_id IN ('nftn','nfta')", "Staff"),
    "project": ("e.auth_id = 'prj_emp'", "Project staff"),
    "retired": ("e.auth_id = 'retd_emp' OR u.auth_id = 'retd_emp'", "Retired"),
    "daily": ("e.auth_id = 'daily_emp' OR u.auth_id = 'daily_emp'", "Daily rated"),
}
EMP_TYPE_LABEL = {"ft": "Faculty", "nftn": "Staff (non-academic)", "nfta": "Staff (academic)",
                  "prj_emp": "Project staff", "retd_emp": "Retired", "daily_emp": "Daily rated"}

# Core tables shown as profile sections (key-value cards), in order. Everything else is a "linked table".
CORE_SECTIONS = [
    ("Account", "users", "id"),
    ("Personal", "user_details", "id"),
    ("Other details", "user_other_details", "id"),
    ("Addresses", "user_address", "id"),
    ("Student academic", "stu_academic", "admn_no"),
    ("Student details", "stu_details", "admn_no"),
    ("Student other details", "stu_other_details", "admn_no"),
    ("Employee", "emp_basic_details", "emp_no"),
    ("Faculty", "faculty_details", "emp_no"),
    ("Institute email (students)", "emaildata", "admission_no"),
    ("Institute email (employees)", "emaildata_emp", "emp_id"),
    ("Roles", "user_auth_types", "id"),
]
CORE_TABLES = {t for _, t, _ in CORE_SECTIONS}

_audit_lock = threading.Lock()


def audit(client: str, action: str, detail: dict):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    line = json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"), "client": client,
                       "action": action, **detail})
    with _audit_lock, open(AUDIT_LOG, "a") as f:
        f.write(line + "\n")


def _q(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _clean(v):
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat(sep=" ") if isinstance(v, datetime.datetime) else v.isoformat()
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


def _mask(v, full: bool = False):
    s = "" if v is None else str(v)
    if not s:
        return s
    if full:   # passwords: reveal nothing, not even the length
        return "••••••••"
    return "•" * max(len(s) - 4, 2) + s[-4:] if len(s) > 4 else "•" * len(s)


# Columns that would be hidden by HIDDEN_COL but that admins may reveal (masked + audit-logged instead).
# user_login_attempts.password = the wrong password typed at a failed MIS login, stored in plain text by the PHP app
# (models/user/users_model.php). Account password hashes (users.password, ci_password) stay hidden.
REVEALABLE = {("user_login_attempts", "password")}


def _shape(rows: list[dict], reveal: bool, table: str = "") -> tuple[list[str], list[dict], list[str]]:
    """Return every column, unmasked. (Hidden/sensitive masking disabled on request.)"""
    if not rows:
        return [], [], []
    cols = list(rows[0])
    out = [{c: _clean(r[c]) for c in cols} for r in rows]
    return cols, out, []


_IS_MARIADB: dict[str, bool] = {}   # per database, detected on first connection


def _timeout_sql(cur, timeout_ms: int, dbk: str) -> str:
    """Session statement-timeout SQL for whichever server we're on (MySQL vs MariaDB differ)."""
    if dbk not in _IS_MARIADB:
        cur.execute("SELECT VERSION() AS v")
        _IS_MARIADB[dbk] = "mariadb" in str(cur.fetchone()["v"]).lower()
    if _IS_MARIADB[dbk]:
        return f"SET SESSION max_statement_time = {int(timeout_ms) / 1000}"   # seconds
    return f"SET SESSION max_execution_time = {int(timeout_ms)}"              # milliseconds


class _Conn:
    """One read-only connection with a statement timeout."""

    def __init__(self, timeout_ms: int = QUERY_TIMEOUT_MS, dbk: str | None = None):
        dbk = db_key(dbk)
        self.conn = ro_connect(dbk)
        with self.conn.cursor() as cur:
            cur.execute(_timeout_sql(cur, timeout_ms, dbk))
            cur.execute("SET SESSION TRANSACTION READ ONLY")

    def all(self, sql, args=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------- search

FIELD_ALIASES = {
    "name": "name", "n": "name", "phone": "phone", "mobile": "phone", "ph": "phone", "contact": "phone",
    "email": "email", "mail": "email", "id": "id", "admn": "id", "admn_no": "id", "emp": "id", "emp_no": "id",
    "roll": "id", "dept": "dept", "department": "dept", "type": "type", "role": "type", "status": "status",
    "father": "father", "course": "course", "branch": "branch", "sem": "semester", "semester": "semester",
    "year": "year", "batch": "year", "designation": "designation", "desig": "designation", "dob": "dob",
    "mother": "mother", "guardian": "guardian", "gender": "gender", "sex": "gender", "category": "category",
    "cat": "category", "blood": "blood", "city": "city", "state": "state", "pincode": "pincode", "pin": "pincode",
    "address": "address", "addr": "address", "level": "level", "stu_type": "level",
    "enroll": "enroll", "enrollment": "enroll", "enrollment_no": "enroll", "via": "via", "admitted": "via",
    "religion": "religion", "nationality": "nationality", "birthplace": "birthplace", "pwd": "pwd",
    "joined": "joined", "joining": "joined", "retires": "retires", "retirement": "retires",
    "nature": "nature", "group": "group", "research": "research", "abc": "abc", "abc_id": "abc",
    "aadhaar": "aadhaar", "aadhar": "aadhaar", "blocked": "blocked",
}

# Grouped for the UI: group -> {field: help}
SEARCH_FIELDS_HELP = {
    "Who": {
        "name": "any part of the name, e.g. name=ravi kumar",
        "id": "admission no. / employee no. (prefix ok)",
        "type": "student | faculty | staff | project | retired | daily",
        "status": "A active, P passed out, L left, I not reported, D deactivated, R retired?, X ex-employee?",
        "blocked": "yes | no - login blocked",
    },
    "Contact": {
        "phone": "own, alternate, address or parent mobile (digits, partial ok)",
        "email": "personal, institute, alternate or parent email",
        "address": "any part of an address line or city",
        "city": "city in any address", "state": "state in any address", "pincode": "pincode (prefix ok)",
    },
    "Personal": {
        "father": "father's name", "mother": "mother's name", "guardian": "guardian's name (students)",
        "dob": "date of birth, YYYY-MM-DD, YYYY-MM or YYYY",
        "gender": "m | f", "category": "GEN, OBC, SC, ST, EWS... (prefix, so cat=obc also matches OBC-NCL)",
        "pwd": "yes | no - physically challenged", "blood": "blood group, e.g. blood=B+",
        "religion": "religion", "nationality": "nationality", "birthplace": "place of birth",
    },
    "Student": {
        "course": "course name or id", "branch": "branch name or id", "sem": "current semester",
        "year": "enrollment year", "level": "ug | pg | jrf | prep | pd",
        "via": "admitted via: iitjee, gate, cat, isme, direct, partjrf...",
        "enroll": "enrollment no.", "abc": "ABC id",
        "aadhaar": "full Aadhaar no. (exact match; redacted in the audit log)",
    },
    "Employee": {
        "dept": "department name or id (students too)", "designation": "designation name",
        "joined": "joining date, YYYY-MM-DD or YYYY", "retires": "retirement date, YYYY-MM-DD or YYYY",
        "nature": "permanent | contract | probation | project ...", "group": "A | B | C",
        "research": "faculty research interest",
    },
}

ONE_WORD_FIELDS = {"type", "status", "id", "semester", "year", "dob", "email", "phone", "gender", "category",
                   "blood", "pincode", "level", "enroll", "pwd", "joined", "retires", "group", "abc", "aadhaar",
                   "blocked", "nature"}

_YES = {"yes", "y", "1", "true"}
# field -> (SQL with %s placeholders, value transform). Every %s gets the transformed value.
SIMPLE_FIELDS = {
    "id": ("u.id LIKE %s", lambda v: v + "%"),
    "status": ("u.status = %s", str.upper),
    "father": ("uod.father_name LIKE %s", lambda v: f"%{v}%"),
    "mother": ("uod.mother_name LIKE %s", lambda v: f"%{v}%"),
    "religion": ("uod.religion LIKE %s", lambda v: f"%{v}%"),
    "nationality": ("uod.nationality LIKE %s", lambda v: f"%{v}%"),
    "birthplace": ("uod.birth_place LIKE %s", lambda v: f"%{v}%"),
    "course": ("COALESCE(cc.name, csc.name, sa.course_id) LIKE %s", lambda v: f"%{v}%"),
    "branch": ("COALESCE(cb.name, csb.name, sa.branch_id) LIKE %s", lambda v: f"%{v}%"),
    "semester": ("sa.semester = %s", None),
    "year": ("sa.enrollment_year LIKE %s", lambda v: v + "%"),
    "via": ("sa.admn_based_on LIKE %s", lambda v: f"%{v}%"),
    "designation": ("des.name LIKE %s", lambda v: f"%{v}%"),
    "dob": ("ud.dob LIKE %s", lambda v: v + "%"),
    "category": ("ud.category LIKE %s", lambda v: v + "%"),
    "joined": ("e.joining_date LIKE %s", lambda v: v + "%"),
    "retires": ("e.retirement_date LIKE %s", lambda v: v + "%"),
    "nature": ("e.employment_nature LIKE %s", lambda v: v + "%"),
    "group": ("e.emp_group = %s", str.upper),
    "city": ("u.id IN (SELECT id FROM user_address WHERE city LIKE %s)", lambda v: f"%{v}%"),
    "state": ("u.id IN (SELECT id FROM user_address WHERE state LIKE %s)", lambda v: f"%{v}%"),
    "pincode": ("u.id IN (SELECT id FROM user_address WHERE pincode LIKE %s)", lambda v: v + "%"),
    "address": ("u.id IN (SELECT id FROM user_address WHERE CONCAT_WS(' ', line1, line2, city) LIKE %s)",
                lambda v: f"%{v}%"),
    "guardian": ("u.id IN (SELECT admn_no FROM stu_other_details WHERE guardian_name LIKE %s)", lambda v: f"%{v}%"),
    "abc": ("u.id IN (SELECT admn_no FROM stu_other_details WHERE abc_id = %s)", None),
    "aadhaar": ("u.id IN (SELECT admn_no FROM stu_other_details WHERE REPLACE(aadhaar_card_no, ' ', '') = %s)",
                lambda v: _digits(v)),
    "enroll": ("u.id IN (SELECT admn_no FROM stu_details WHERE enrollment_no LIKE %s)", lambda v: v + "%"),
    "level": ("u.id IN (SELECT admn_no FROM stu_details WHERE stu_type = %s)", str.lower),
    "research": ("u.id IN (SELECT emp_no FROM faculty_details WHERE research_interest LIKE %s)", lambda v: f"%{v}%"),
    "blood": ("u.id IN (SELECT admn_no FROM stu_details WHERE REPLACE(blood_group, ' ', '') = %s "
              "UNION SELECT emp_no FROM emp_basic_details WHERE REPLACE(blood_group, ' ', '') = %s)",
              lambda v: v.replace(" ", "").upper()),
    "pwd": ("ud.physically_challenged = %s", lambda v: "yes" if v.lower() in _YES else "no"),
    "blocked": ("u.is_blocked = %s", lambda v: 1 if v.lower() in _YES else 0),
}
SENSITIVE_FIELDS = {"aadhaar"}


def redact_query(q: str) -> str:
    """Query text for the audit log, with sensitive field values removed."""
    fields, _ = parse_query(q)
    for k in SENSITIVE_FIELDS & fields.keys():
        q = q.replace(fields[k], "[redacted]")
    return q
_TOKEN = re.compile(r'(\w+)\s*[=:]\s*("([^"]*)"|\'([^\']*)\'|(.+?))(?=\s+\w+\s*[=:]|$)')


def parse_query(q: str) -> tuple[dict, str]:
    """'name=ravi kumar phone=98765 cse' -> ({'name': 'ravi kumar', 'phone': '98765'}, 'cse')."""
    fields, consumed, leftovers = {}, [], []
    for m in _TOKEN.finditer(q):
        key = FIELD_ALIASES.get(m.group(1).lower())
        if not key:
            continue
        val = next(g for g in (m.group(3), m.group(4), m.group(5)) if g is not None).strip()
        if key in ONE_WORD_FIELDS and m.group(5) is not None and " " in val:
            val, extra = val.split(" ", 1)
            consumed.append(m.span())
            fields[key] = val
            leftovers.append(extra)
            continue
        if val:
            fields[key] = val
            consumed.append(m.span())
    rest = q
    for a, b in sorted(consumed, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    return fields, " ".join((rest + " " + " ".join(leftovers)).split())


def _digits(s):
    return re.sub(r"\D", "", s)


def search(q: str, limit: int = 100, dbk: str | None = None) -> dict:
    fields, free = parse_query(q)
    where, args = [], []

    def like(v):
        return f"%{v}%"

    def phone_clause(v):
        d = _digits(v)
        if len(d) < 3:
            return None
        p = like(d)
        args.extend([p, p, p, p, p])
        return ("u.id IN (SELECT id FROM user_other_details WHERE mobile_no LIKE %s "
                "UNION SELECT id FROM user_address WHERE contact_no LIKE %s "
                "UNION SELECT admn_no FROM stu_details WHERE parent_mobile_no LIKE %s OR alternate_mobile_no LIKE %s "
                "UNION SELECT admission_no FROM emaildata WHERE phn_no LIKE %s)")

    def email_clause(v):
        p = like(v)
        args.extend([p, p, p, p, p])
        return ("(ud.email LIKE %s OR u.id IN (SELECT admission_no FROM emaildata WHERE domain_name LIKE %s "
                "UNION SELECT emp_id FROM emaildata_emp WHERE domain_name LIKE %s "
                "UNION SELECT admn_no FROM stu_details WHERE alternate_email_id LIKE %s OR parent_email_id LIKE %s))")

    def name_clause(v):
        parts = []
        for w in v.split():
            parts.append("CONCAT_WS(' ', ud.first_name, ud.middle_name, ud.last_name) LIKE %s")
            args.append(like(w))
        return "(" + " AND ".join(parts) + ")"

    for key, val in fields.items():
        if key == "name":
            where.append(name_clause(val))
        elif key == "phone":
            c = phone_clause(val)
            if c:
                where.append(c)
        elif key == "email":
            where.append(email_clause(val))
        elif key == "dept":
            where.append("(d.name LIKE %s OR d.id = %s)")
            args.extend([like(val), val])
        elif key == "type":
            t = PERSON_TYPES.get(val.lower().rstrip("s"))
            if t:
                where.append(f"({t[0]})")
        elif key == "gender":
            g = val[:1].lower()
            where.append("ud.sex IN (%s, %s)")
            args.extend([g, {"m": "male", "f": "female"}.get(g, g)])
        elif key in SIMPLE_FIELDS:
            sql, fn = SIMPLE_FIELDS[key]
            where.append(sql)
            args.extend([fn(val) if fn else val] * sql.count("%s"))

    if free:  # no field given: match name, id, email or phone
        sub = [name_clause(free), "u.id LIKE %s"]
        args.append(free + "%")
        if "@" in free or "." in free:
            sub.append(email_clause(free))
        pc = phone_clause(free) if _digits(free) == free.replace(" ", "") else None
        if pc:
            sub.append(pc)
        where.append("(" + " OR ".join(sub) + ")")

    if not where:
        return {"fields": fields, "free": free, "results": [], "message": "Type a name, id, phone or email."}

    sql = f"""
        SELECT u.id, u.auth_id, u.status,
               CONCAT_WS(' ', ud.salutation, ud.first_name, ud.middle_name, ud.last_name) AS name,
               ud.sex, d.name AS dept, ud.email, uod.mobile_no,
               e.auth_id AS emp_type, des.name AS designation,
               COALESCE(cc.name, csc.name, sa.course_id) AS course, COALESCE(cb.name, csb.name, sa.branch_id) AS branch,
               sa.semester, sa.enrollment_year
        FROM users u
        JOIN user_details ud ON ud.id = u.id
        LEFT JOIN departments d ON d.id = ud.dept_id
        LEFT JOIN user_other_details uod ON uod.id = u.id
        LEFT JOIN emp_basic_details e ON e.emp_no = u.id
        LEFT JOIN designations des ON des.id = e.designation
        LEFT JOIN stu_academic sa ON sa.admn_no = u.id
        LEFT JOIN cbcs_courses cc ON cc.id = sa.course_id
        LEFT JOIN cs_courses csc ON csc.id = sa.course_id AND cc.id IS NULL
        LEFT JOIN cbcs_branches cb ON cb.id = sa.branch_id
        LEFT JOIN cs_branches csb ON csb.id = sa.branch_id AND cb.id IS NULL
        WHERE {' AND '.join(where)}
        ORDER BY ud.first_name, ud.last_name
        LIMIT {int(limit) + 1}"""
    started = time.time()
    db = _Conn(dbk=dbk)
    try:
        rows = db.all(sql, args)
    finally:
        db.close()
    results = []
    for r in rows[:limit]:
        r = {k: _clean(v) for k, v in r.items()}
        r["type"] = "Student" if r["auth_id"] == "stu" else EMP_TYPE_LABEL.get(r["emp_type"] or "", r["auth_id"])
        results.append(r)
    return {"fields": fields, "free": free, "results": results, "more": len(rows) > limit,
            "ms": int((time.time() - started) * 1000)}


# ---------------------------------------------------------------- profile

def profile(pid: str, reveal: bool = False, dbk: str | None = None) -> dict:
    db = _Conn(dbk=dbk)
    try:
        if not db.all("SELECT 1 FROM users WHERE id = %s", (pid,)):
            if not db.all("SELECT 1 FROM user_details WHERE id = %s", (pid,)):
                return {"found": False, "id": pid}
        sections = []
        for title, table, key in CORE_SECTIONS:
            if table not in TABLES:
                continue
            rows = db.all(f"SELECT * FROM {_q(table)} WHERE {_q(key)} = %s LIMIT 20", (pid,))
            cols, rows, masked = _shape(rows, reveal, table)
            if rows:
                sections.append({"title": title, "table": table, "columns": cols, "rows": rows, "masked": masked})
        # Lookups that turn codes into names
        summary = db.all("""
            SELECT u.id, u.auth_id, u.status,
                   CONCAT_WS(' ', ud.salutation, ud.first_name, ud.middle_name, ud.last_name) AS name,
                   ud.photopath, d.name AS dept, des.name AS designation, e.auth_id AS emp_type,
                   at.type AS emp_type_name,
                   COALESCE(cc.name, csc.name, sa.course_id) AS course, COALESCE(cb.name, csb.name, sa.branch_id) AS branch,
                   sa.semester, sa.enrollment_year
            FROM user_details ud
            LEFT JOIN users u ON u.id = ud.id
            LEFT JOIN departments d ON d.id = ud.dept_id
            LEFT JOIN emp_basic_details e ON e.emp_no = ud.id
            LEFT JOIN designations des ON des.id = e.designation
            LEFT JOIN auth_types at ON at.id = e.auth_id
            LEFT JOIN stu_academic sa ON sa.admn_no = ud.id
            LEFT JOIN cbcs_courses cc ON cc.id = sa.course_id
            LEFT JOIN cs_courses csc ON csc.id = sa.course_id AND cc.id IS NULL
            LEFT JOIN cbcs_branches cb ON cb.id = sa.branch_id
            LEFT JOIN cs_branches csb ON csb.id = sa.branch_id AND cb.id IS NULL
            WHERE ud.id = %s""", (pid,))
        s = {k: _clean(v) for k, v in summary[0].items()} if summary else {"id": pid}
        s["type"] = "Student" if s.get("auth_id") == "stu" else EMP_TYPE_LABEL.get(s.get("emp_type") or "", s.get("auth_id"))
    finally:
        db.close()
    return {"found": True, "id": pid, "summary": s, "sections": sections}


# ---------------------------------------------------------------- linked tables

def link_plan() -> tuple[list[tuple], list[tuple]]:
    """(auto, on_demand) lists of (table, [key columns]) for every non-core table holding a person id."""
    auto, on_demand = [], []
    for name, t in TABLES.items():
        keys = t.get("person_keys")
        if not keys or name in CORE_TABLES or t["type"] != "BASE TABLE" or t.get("is_backup_like"):
            continue
        indexed = set(t.get("indexed", []))
        if all(k.lower() in indexed for k in keys) or t.get("approx_rows", 0) < LARGE_UNINDEXED_ROWS:
            auto.append((name, keys))
        else:
            on_demand.append((name, keys))
    return auto, on_demand


def _fetch_link(db: _Conn, table: str, keys: list[str], pid: str, reveal: bool):
    cond = " OR ".join(f"{_q(k)} = %s" for k in keys)
    order = f" ORDER BY {LINK_ORDER[table]}" if table in LINK_ORDER else ""
    rows = db.all(f"SELECT * FROM {_q(table)} WHERE {cond}{order} LIMIT {LINK_ROW_LIMIT + 1}", [pid] * len(keys))
    if not rows:
        return None
    cols, shaped, masked = _shape(rows[:LINK_ROW_LIMIT], reveal, table)
    t = TABLES[table]
    return {"table": table, "module": t["module"], "keys": keys, "columns": cols, "rows": shaped,
            "more": len(rows) > LINK_ROW_LIMIT, "masked": masked, "approx_table_rows": t.get("approx_rows", 0)}


def stream_links(pid: str, reveal: bool = False, dbk: str | None = None):
    """Yields events: plan, then one 'link' per table that has rows for this person, then done."""
    auto, on_demand = link_plan()
    yield {"type": "plan", "auto": len(auto),
           "on_demand": [{"table": n, "keys": k, "approx_rows": TABLES[n].get("approx_rows", 0)} for n, k in on_demand]}
    started = time.time()
    local = threading.local()
    conns, conns_lock = [], threading.Lock()

    def work(item):
        if not hasattr(local, "db"):
            local.db = _Conn(timeout_ms=10_000, dbk=dbk)
            with conns_lock:
                conns.append(local.db)
        table, keys = item
        try:
            return _fetch_link(local.db, table, keys, pid, reveal), None
        except Exception as e:  # timeouts / odd tables: report, keep going
            return None, {"table": table, "error": f"{type(e).__name__}: {e}"[:200]}

    found = errors = 0
    try:
        with cf.ThreadPoolExecutor(max_workers=LINK_WORKERS) as pool:
            for res, err in pool.map(work, auto):
                if res:
                    found += 1
                    yield {"type": "link", **res}
                elif err:
                    errors += 1
                    yield {"type": "link_error", **err}
    finally:
        for c in conns:
            c.close()
    yield {"type": "done", "found": found, "searched": len(auto), "errors": errors,
           "ms": int((time.time() - started) * 1000)}


def scan_one(pid: str, table: str, reveal: bool = False, dbk: str | None = None) -> dict:
    t = TABLES.get(table)
    if not t or not t.get("person_keys"):
        return {"table": table, "error": "Not a person-linked table."}
    db = _Conn(timeout_ms=60_000, dbk=dbk)
    try:
        res = _fetch_link(db, table, t["person_keys"], pid, reveal)
    finally:
        db.close()
    return res or {"table": table, "module": t["module"], "rows": [], "columns": [], "empty": True}


# ---------------------------------------------------------------- status labels + value suggestions

# users.status meanings, from the PHP code (payment_admin views, newadmission_reporting, employee/remove).
# "sure": False = inferred from who has the code, not stated in code.
STATUS_LABELS = {
    "A": {"label": "Active", "sure": True},
    "P": {"label": "Passed out", "sure": True},
    "L": {"label": "Left", "sure": True},
    "I": {"label": "Not yet reported", "sure": True, "note": "admitted, hasn't reported; set to A on reporting"},
    "D": {"label": "Deactivated", "sure": True, "note": "set when an employee record is removed"},
    "R": {"label": "Retired", "sure": False, "note": "likely: almost all are employees; not set anywhere in the code"},
    "X": {"label": "Ex-employee", "sure": False, "note": "likely: mostly project staff; not set anywhere in the code"},
    "E": {"label": "Code E", "sure": False, "note": "meaning unknown; 6 accounts"},
}

_STATIC_SUGGEST = {
    "type": [("student", "Students"), ("faculty", "Faculty"), ("staff", "Non-faculty staff"), ("project", "Project staff"),
             ("retired", "Retired"), ("daily", "Daily rated")],
    "status": [(k, v["label"] + ("" if v["sure"] else " (likely)")) for k, v in STATUS_LABELS.items()],
    "level": [("ug", "Undergraduate"), ("pg", "Postgraduate"), ("jrf", "Research (JRF / PhD)"), ("prep", "Preparatory"), ("pd", "Post-doc")],
    "gender": [("m", "Male"), ("f", "Female")],
    "pwd": [("yes", "Physically challenged"), ("no", "Not physically challenged")],
    "blocked": [("yes", "Login blocked"), ("no", "Not blocked")],
    "group": [("A", "Group A"), ("B", "Group B"), ("C", "Group C")],
    "blood": [(b, "") for b in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")],
    "semester": [(str(i), "") for i in range(1, 11)],
}
# field -> SQL returning (value, people) for distinct lookup values. Only code/lookup values, never personal data.
_SQL_SUGGEST = {
    "dept": "SELECT d.name, COUNT(ud.id) FROM departments d LEFT JOIN user_details ud ON ud.dept_id = d.id GROUP BY d.id, d.name",
    "designation": "SELECT des.name, COUNT(e.emp_no) FROM designations des LEFT JOIN emp_basic_details e ON e.designation = des.id GROUP BY des.id, des.name",
    "course": "SELECT name, NULL FROM cbcs_courses UNION SELECT name, NULL FROM cs_courses",
    "branch": "SELECT name, NULL FROM cbcs_branches UNION SELECT name, NULL FROM cs_branches",
    "city": "SELECT city, COUNT(DISTINCT id) FROM user_address WHERE city <> '' GROUP BY city HAVING COUNT(DISTINCT id) >= 5",
    "category": "SELECT category, COUNT(*) FROM user_details WHERE category <> '' GROUP BY category",
    "via": "SELECT admn_based_on, COUNT(*) FROM stu_academic WHERE admn_based_on <> '' AND admn_based_on <> '0' GROUP BY admn_based_on",
    "nature": "SELECT employment_nature, COUNT(*) FROM emp_basic_details WHERE employment_nature <> '' GROUP BY employment_nature",
    "year": "SELECT enrollment_year, COUNT(*) FROM stu_academic WHERE enrollment_year > 0 GROUP BY enrollment_year ORDER BY enrollment_year DESC",
    "state": "SELECT state, COUNT(DISTINCT id) FROM user_address WHERE state <> '' GROUP BY state HAVING COUNT(DISTINCT id) >= 5",
    "religion": "SELECT religion, COUNT(*) FROM user_other_details WHERE religion <> '' GROUP BY religion HAVING COUNT(*) >= 5",
    "nationality": "SELECT nationality, COUNT(*) FROM user_other_details WHERE nationality <> '' GROUP BY nationality HAVING COUNT(*) >= 3",
}
_suggest_cache: dict[tuple[str, str], list] = {}   # (database, field) -> values
_suggest_lock = threading.Lock()


def _suggest_values(field: str, dbk: str | None = None) -> list[dict]:
    if field in _STATIC_SUGGEST:
        return [{"value": v, "hint": h} for v, h in _STATIC_SUGGEST[field]]
    sql = _SQL_SUGGEST.get(field)
    if not sql:
        return []
    with _suggest_lock:
        ck = (db_key(dbk), field)
        if ck not in _suggest_cache:
            db = _Conn(timeout_ms=10_000, dbk=dbk)
            try:
                rows = db.all(sql)
            finally:
                db.close()
            seen, out = set(), []
            for r in rows:
                v, n = list(r.values())
                v = str(_clean(v) or "").strip()
                if v and v.lower() not in seen:
                    seen.add(v.lower())
                    out.append({"value": v, "count": int(n) if n is not None else None})
            if field != "year":
                out.sort(key=lambda x: -(x["count"] or 0))
            _suggest_cache[ck] = out
        return _suggest_cache[ck]


def suggest(field: str, prefix: str = "", limit: int = 12, dbk: str | None = None) -> dict:
    field = FIELD_ALIASES.get(field.lower(), field.lower())
    p = prefix.lower().strip()
    vals = _suggest_values(field, dbk)
    if p:
        starts = [v for v in vals if v["value"].lower().startswith(p)]
        inside = [v for v in vals if p in v["value"].lower() and v not in starts]
        vals = starts + inside
    return {"field": field, "values": vals[:limit], "enumerable": field in _STATIC_SUGGEST or field in _SQL_SUGGEST}
