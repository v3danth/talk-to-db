"""Schema map lookups (backs the Schema view): keyword search over catalog.json and per-table details."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = json.load(open(os.path.join(HERE, "catalog.json")))
TABLES = CATALOG["tables"]
TABLES_LOWER = {k.lower(): k for k in TABLES}

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
