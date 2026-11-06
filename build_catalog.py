"""Build a schema catalog (the "map") of the MIS database.

Reads only metadata (information_schema) plus the PHP source code - never row data.
Produces:
  catalog.json   - machine-readable map used by the talk-to-db agent
  SCHEMA_MAP.md  - human-readable map: modules, core tables, join graph

Usage: .venv/bin/python build_catalog.py [--code ~/Projects/MIS_code/application]   (or set MIS_CODE_DIR)
"""
import argparse
import collections
import json
import os
import re

import pymysql

from config import DB_NAME, admin_connect

MODULE_LABELS = {
    "adm": "Admissions (per-programme: mtech, phd, mba, bsced, ...)",
    "acc": "Accounts / payroll / GPF / income tax",
    "accounts": "Accounts - sponsored projects",
    "cbcs": "CBCS academics (courses, attendance, marks) - older curriculum",
    "nep": "NEP academics (courses, attendance, marks, results) - current curriculum",
    "reg": "Semester registration (forms, fees)",
    "stu": "Student master data",
    "emp": "Employee master data",
    "user": "Users / identity / auth",
    "users": "Users / identity / auth",
    "auth": "Authorisation / menus / roles",
    "sleave": "Student leave (keyed by admn_no)",
    "leave": "Employee leave",
    "hs": "Hostels",
    "hc": "Health centre",
    "fbs": "Feedback system",
    "fellow": "Fellowships (JRF/SRF bills)",
    "final": "Final semester-wise marks / grade sheets",
    "online": "Online payments",
    "payment": "Payments",
    "bank": "Bank fee details",
    "tms": "Thesis management",
    "schlr": "Scholarships",
    "complaint": "Complaints",
    "convocation": "Convocation",
    "absent": "Attendance (absent records)",
    "pre": "Pre-registration / course allotment",
    "no": "No-dues",
    "apar": "APAR (faculty appraisal)",
    "stock": "Stock / inventory",
    "abc": "Academic Bank of Credits",
    "exam": "Examinations",
    "ft": "Faculty tools",
    "tt": "Timetable",
    "drop": "Course/student drops",
    "jrf": "JRF",
    "cdc": "Career Development Centre / placements",
    "tp": "Training & placement",
    "guard": "Security guards",
    "lib": "Library",
    "project": "Projects",
    "info": "Information / notices",
}

JUNK_RE = re.compile(
    r"(bkp|backup|_old|old_|old-|copy|_temp|temp_|_tmp|tmp_|test|_bak|_stop|stopped|incorrect|duplicate|wrong|"
    r"\d{1,2}[_\-]\d{1,2}[_\-]\d{2,4}|\d{6,8}|--|before|original)",
    re.I,
)
TEMPLATE_RE = re.compile(r"templat", re.I)
PERSON_KEY_RE = re.compile(
    r"^(admn_no|admission_no|adm_no|admno|stu_id|student_id|emp_no|empno|emp_id|employee_id|user_id|userid|faculty_id|regno"
    r"|teacher_id|guide_id|supervisor_id|co_supervisor_id|coordinator_id|hod_id|mentor_id|advisor_id|faculty_advisor_id"
    r"|instructor_id|examiner_id|warden_id|pi_id|emp_code)$",
    re.I)


def is_junk_name(name: str) -> bool:
    low = name.lower()
    return bool(JUNK_RE.search(low.replace("template", "")))


def module_of(name: str) -> str:
    return name.lower().split("_", 1)[0]


def fetch_metadata(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, table_type, IFNULL(table_rows,0), IFNULL(data_length+index_length,0), "
            "IFNULL(table_comment,'') FROM information_schema.tables WHERE table_schema=%s",
            (DB_NAME,),
        )
        tables = {
            r[0]: {"name": r[0], "type": r[1], "approx_rows": int(r[2]), "bytes": int(r[3]), "comment": r[4]}
            for r in cur.fetchall()
        }
        cur.execute(
            "SELECT table_name, column_name, column_type, column_key, is_nullable, IFNULL(column_comment,'') "
            "FROM information_schema.columns WHERE table_schema=%s ORDER BY table_name, ordinal_position",
            (DB_NAME,),
        )
        for t, col, ctype, key, nullable, comment in cur.fetchall():
            if t not in tables:
                continue
            c = {"name": col, "type": ctype}
            if key:
                c["key"] = key
            if nullable == "NO":
                c["not_null"] = True
            if comment:
                c["comment"] = comment
            tables[t].setdefault("columns", []).append(c)
        cur.execute(
            "SELECT table_name, column_name, referenced_table_name, referenced_column_name "
            "FROM information_schema.key_column_usage WHERE table_schema=%s AND referenced_table_name IS NOT NULL",
            (DB_NAME,),
        )
        fks = [
            {"from": f"{a}.{b}", "to": f"{c}.{d}", "source": "declared_fk"}
            for a, b, c, d in cur.fetchall()
        ]
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.statistics "
            "WHERE table_schema=%s AND seq_in_index=1", (DB_NAME,)
        )
        for t, col in cur.fetchall():
            if t in tables:
                tables[t].setdefault("indexed", set()).add(col.lower())
        cur.execute(
            "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema=%s", (DB_NAME,)
        )
        for name, definition in cur.fetchall():
            if name in tables:
                tables[name]["view_definition"] = definition
    return tables, fks


def mine_code(code_root: str, tables: dict):
    """Find which code files use each table, and the JOIN conditions the code uses."""
    by_lower = {t.lower(): t for t in tables}
    tok = re.compile(r"[A-Za-z0-9_\-]+")
    # FROM/JOIN <table> [AS] <alias>, plus CodeIgniter ->join('table alias', 'a.x = b.y')
    from_join = re.compile(r"\b(?:from|join)\s+`?([A-Za-z0-9_]+)`?(?:\s+(?:as\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?)?", re.I)
    ci_join = re.compile(r"->join\(\s*['\"]`?([A-Za-z0-9_]+)`?(?:\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*))?['\"]\s*,\s*['\"]([^'\"]+)['\"]", re.I)
    ci_from = re.compile(r"->(?:from|get|get_where|insert|update|delete)\(\s*['\"]`?([A-Za-z0-9_]+)`?(?:\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*))?['\"]", re.I)
    cond = re.compile(r"`?([A-Za-z_][A-Za-z0-9_]*)`?\.`?([A-Za-z_][A-Za-z0-9_]*)`?\s*=\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\.`?([A-Za-z_][A-Za-z0-9_]*)`?")
    sql_kw = {"on", "where", "left", "right", "inner", "outer", "join", "group", "order", "limit", "set", "using", "and", "union", "cross", "natural", "straight_join"}

    used_in = collections.defaultdict(set)
    joins = collections.Counter()
    for dirpath, _, files in os.walk(code_root):
        for fname in files:
            if not fname.endswith(".php"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                text = open(path, errors="ignore").read()
            except OSError:
                continue
            rel = os.path.relpath(path, code_root)
            low = text.lower()
            for w in set(tok.findall(low)):
                if w in by_lower:
                    used_in[by_lower[w]].add(rel)
            # Resolve aliases per file (good enough; ambiguous aliases are dropped)
            alias = collections.defaultdict(set)
            for m in list(from_join.finditer(text)) + list(ci_from.finditer(text)):
                t = by_lower.get(m.group(1).lower())
                if not t:
                    continue
                alias[t.lower()].add(t)
                a = (m.group(2) or "").lower()
                if a and a not in sql_kw:
                    alias[a].add(t)
            conds = [m for m in cond.finditer(text)]
            for m in ci_join.finditer(text):
                t = by_lower.get(m.group(1).lower())
                if t:
                    alias[t.lower()].add(t)
                    if m.group(2) and m.group(2).lower() not in sql_kw:
                        alias[m.group(2).lower()].add(t)
            for m in conds:
                a1, c1, a2, c2 = m.group(1).lower(), m.group(2), m.group(3).lower(), m.group(4)
                if len(alias.get(a1, ())) != 1 or len(alias.get(a2, ())) != 1:
                    continue
                t1, t2 = next(iter(alias[a1])), next(iter(alias[a2]))
                if t1 == t2:
                    continue
                cols1 = {c["name"].lower() for c in tables[t1].get("columns", [])}
                cols2 = {c["name"].lower() for c in tables[t2].get("columns", [])}
                if c1.lower() not in cols1 or c2.lower() not in cols2:
                    continue
                edge = tuple(sorted([f"{t1}.{c1}", f"{t2}.{c2}"]))
                joins[edge] += 1
    return used_in, joins


def load_list(path):
    if not os.path.exists(path):
        return set()
    return {l.strip() for l in open(path) if l.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=os.environ.get("MIS_CODE_DIR", os.path.expanduser("~/Projects/MIS_code/application")))
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))

    conn = admin_connect()
    tables, fks = fetch_metadata(conn)
    conn.close()
    used_in, joins = mine_code(args.code, tables)

    # Tables slated for dropping are kept out of the map so the agent never relies on them.
    drop = set()
    for f in ("cleanup/tier1_backup_and_dated_copies.sql", "cleanup/tier2_empty_unreferenced.sql"):
        p = os.path.join(here, f)
        if os.path.exists(p):
            drop |= set(re.findall(r"^DROP TABLE IF EXISTS `([^`]+)`", open(p).read(), re.M))

    out_tables = {}
    for name, t in tables.items():
        if name in drop:
            continue
        files = sorted(used_in.get(name, ()))
        controllers = sorted({f.split(os.sep)[1] for f in files if f.startswith("controllers" + os.sep) and len(f.split(os.sep)) > 2}
                             | {os.path.splitext(f.split(os.sep)[1])[0] for f in files if f.startswith("controllers" + os.sep) and len(f.split(os.sep)) == 2})
        t["module"] = module_of(name)
        t["code_refs"] = len(files)
        t["used_by"] = controllers[:12]
        # Snapshot rule: "<live_table>_<digits>" (e.g. nep_absent_table_course_wise_2103) is a dated copy.
        base = re.sub(r"_\d{2,8}$", "", name)
        t["is_backup_like"] = is_junk_name(name) or (base != name and base in tables)
        if base != name and base in tables:
            t["snapshot_of"] = base
        out_tables[name] = t

    relationships = [r for r in fks if r["from"].split(".")[0] in out_tables and r["to"].split(".")[0] in out_tables]
    for (a, b), n in joins.most_common():
        if a.split(".")[0] in out_tables and b.split(".")[0] in out_tables:
            relationships.append({"from": a, "to": b, "source": "code_join", "uses": n})

    # Per-table neighbour list for fast describe
    for r in relationships:
        for x, y in ((r["from"], r["to"]), (r["to"], r["from"])):
            out_tables[x.split(".")[0]].setdefault("joins", []).append(
                {"on": f"{x} = {y}", "source": r["source"], "uses": r.get("uses", 0)}
            )
    for t in out_tables.values():
        if "joins" in t:
            t["joins"].sort(key=lambda j: (j["source"] != "declared_fk", -j["uses"]))
            t["joins"] = t["joins"][:25]

    # Person-key map: which column(s) of each table hold a person's id (users.id = admn_no / emp_no).
    # Sources: well-known key column names + any column the code joins to a person table's id.
    person_anchor = {"users.id", "user_details.id", "stu_academic.admn_no", "stu_details.admn_no",
                     "emp_basic_details.emp_no", "user_other_details.id"}
    joined_to_person = collections.defaultdict(set)
    for r in relationships:
        for x, y in ((r["from"], r["to"]), (r["to"], r["from"])):
            if y in person_anchor and x not in person_anchor:
                tbl, col = x.split(".", 1)
                joined_to_person[tbl].add(col)
    for name, t in out_tables.items():
        cols = {c["name"]: c for c in t.get("columns", [])}
        keys = {c for c in cols if PERSON_KEY_RE.match(c)} | joined_to_person.get(name, set())
        keys = sorted(c for c in keys if c in cols and re.match(r"(var)?char", cols[c]["type"]))
        if keys:
            t["person_keys"] = keys
        t["indexed"] = sorted(t.get("indexed", ()))

    # Hub score: how central a table is (joins + code usage + size)
    degree = collections.Counter()
    for r in relationships:
        degree[r["from"].split(".")[0]] += 1
        degree[r["to"].split(".")[0]] += 1
    for name, t in out_tables.items():
        t["hub_score"] = degree[name] * 3 + min(t["code_refs"], 200) / 10

    modules = collections.defaultdict(list)
    for name, t in out_tables.items():
        modules[t["module"]].append(name)
    module_summary = {}
    for m, names in modules.items():
        names.sort(key=lambda n: -out_tables[n]["hub_score"])
        module_summary[m] = {
            "label": MODULE_LABELS.get(m, ""),
            "table_count": len(names),
            "core_tables": [n for n in names if not out_tables[n]["is_backup_like"]][:15],
        }

    catalog = {
        "database": DB_NAME,
        "tables": out_tables,
        "relationships": relationships,
        "modules": dict(sorted(module_summary.items(), key=lambda kv: -kv[1]["table_count"])),
    }
    with open(os.path.join(here, "catalog.json"), "w") as f:
        json.dump(catalog, f)
    write_markdown(catalog, os.path.join(here, "SCHEMA_MAP.md"))
    print(f"tables mapped: {len(out_tables)} (excluded {len(drop & set(tables))} drop candidates)")
    print(f"relationships: {sum(1 for r in relationships if r['source']=='declared_fk')} declared FK, "
          f"{sum(1 for r in relationships if r['source']=='code_join')} mined from code")
    print(f"modules: {len(module_summary)}")


def write_markdown(cat, path):
    t = cat["tables"]
    lines = [f"# Schema map: `{cat['database']}`", "",
             f"{len(t)} tables/views, {len(cat['relationships'])} relationships "
             "(declared foreign keys + JOIN conditions mined from the PHP code). Generated by `build_catalog.py`.", "",
             "## Modules", "", "| Module prefix | What it is | Tables | Core tables (most connected first) |", "|---|---|---|---|"]
    for m, s in cat["modules"].items():
        if s["table_count"] < 2:
            continue
        lines.append(f"| `{m}_` | {s['label']} | {s['table_count']} | {', '.join('`'+x+'`' for x in s['core_tables'][:8])} |")
    hubs = sorted(t.values(), key=lambda x: -x["hub_score"])[:40]
    lines += ["", "## Hub tables (the centre of the graph)", "", "| Table | ~Rows | Columns | Joins to |", "|---|---|---|---|"]
    for h in hubs:
        partners = []
        for j in h.get("joins", []):
            other = j["on"].split(" = ")[1].split(".")[0]
            if other not in partners:
                partners.append(other)
        lines.append(f"| `{h['name']}` | {h['approx_rows']:,} | {len(h.get('columns', []))} | {', '.join('`'+p+'`' for p in partners[:8])} |")
    lines += ["", "## Strongest join paths (by how often the code uses them)", "", "| Join | Times used in code |", "|---|---|"]
    for r in [r for r in cat["relationships"] if r["source"] == "code_join"][:80]:
        lines.append(f"| `{r['from']}` = `{r['to']}` | {r['uses']} |")
    fk = [r for r in cat["relationships"] if r["source"] == "declared_fk"]
    lines += ["", f"## Declared foreign keys ({len(fk)})", ""]
    lines += [f"- `{r['from']}` -> `{r['to']}`" for r in fk]
    open(path, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
