"""Generate DB_RELATIONSHIPS.html (+ DB_RELATIONSHIPS.md) - how mis_40_50 fits together.

Built only from catalog.json (schema metadata + joins mined from the PHP code). Every edge in the
diagrams is a declared foreign key or a JOIN the application code really performs.
Usage: .venv/bin/python build_relationships_doc.py
"""
import collections
import html
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(HERE, "catalog.json")))
T, REL = CAT["tables"], CAT["relationships"]

DOMAINS = [
    {
        "key": "identity", "title": "1. People: the identity core", "root": "users",
        "tables": ["users", "user_details", "user_other_details", "user_address", "user_auth_types", "auth_types",
                   "departments", "stu_academic", "stu_details", "stu_other_details", "emp_basic_details",
                   "designations", "faculty_details", "emp_pay_details", "emp_family_details", "emaildata", "emaildata_emp"],
        "text": """
<p>Everyone (student, professor, staff member) is <b>one row in <code>users</code></b>. Its <code>id</code> is the
admission number for students and the employee number for employees. The same value is the key everywhere else, under
names like <code>admn_no</code>, <code>emp_no</code>, <code>EMPNO</code>, <code>emp_id</code> or <code>admission_no</code>.</p>
<ul>
<li><code>users</code>: login, role code <code>auth_id</code> (<code>stu</code>, <code>emp</code>, <code>prj_emp</code>, <code>daily_emp</code>, ...) and account <code>status</code> (<code>A</code> = active).</li>
<li><code>user_details</code> (1:1): name, sex, category, DOB, email, <code>dept_id</code> &rarr; <code>departments</code>.</li>
<li><code>user_other_details</code> (1:1): mobile, father/mother name, bank details. <code>user_address</code> (1:many): addresses with <code>contact_no</code>.</li>
<li>Roles: <code>user_auth_types</code> (1:many) &rarr; <code>auth_types</code>. One person can hold several roles.</li>
<li><b>Students</b> extend with <code>stu_academic</code> (course, branch, current semester, enrollment year), <code>stu_details</code> (parent and alternate contacts), <code>stu_other_details</code> (guardian, Aadhaar, ABC id).</li>
<li><b>Employees</b> extend with <code>emp_basic_details</code>. Its <code>auth_id</code> separates <b>faculty (<code>ft</code>)</b>, non-faculty academic (<code>nfta</code>), non-faculty non-academic (<code>nftn</code>), project staff (<code>prj_emp</code>) and retired (<code>retd_emp</code>); <code>designation</code> &rarr; <code>designations</code>. Also <code>faculty_details</code>, <code>emp_pay_details</code>, <code>emp_family_details</code>.</li>
<li>Institute mail accounts: <code>emaildata</code> (students, by <code>admission_no</code>) and <code>emaildata_emp</code> (employees, by <code>emp_id</code>).</li>
</ul>""",
    },
    {
        "key": "curriculum", "title": "2. Programmes and subjects", "root": "departments",
        "tables": ["departments", "dept_course", "course_branch", "cs_courses", "cs_branches", "course_structure",
                   "subject_mapping", "subject_mapping_des", "cbcs_courses", "cbcs_branches", "cbcs_departments",
                   "cbcs_subject_offered", "cbcs_subject_offered_desc", "cbcs_credit_points_master",
                   "nep_credit_points_master"],
        "text": """
<p>A <b>programme</b> is a course + branch pair (<code>course_branch</code> &rarr; <code>cs_courses</code>, <code>cs_branches</code>),
attached to a department through <code>dept_course</code>, which carries an <code>aggr_id</code> (the curriculum version).</p>
<ul>
<li>Older scheme: <code>course_structure</code> (subjects per <code>aggr_id</code> and semester) &rarr; <code>subject_mapping</code> (offered in a session) with teachers in <code>subject_mapping_des</code>.</li>
<li>CBCS scheme: <code>cbcs_subject_offered</code> (+ <code>_desc</code> for faculty and components) per dept/course/branch/session, with <code>cbcs_courses</code>, <code>cbcs_branches</code>, <code>cbcs_departments</code> and credit rules in <code>cbcs_credit_points_master</code>.</li>
<li>NEP scheme (current batches) mirrors CBCS with <code>nep_*</code> tables. Much of it is used by a second application whose code isn't in this repo, so fewer joins are mined for it.</li>
</ul>""",
    },
    {
        "key": "registration", "title": "3. Semester registration and fees", "root": "reg_regular_form",
        "tables": ["reg_regular_form", "reg_regular_fee", "reg_regular_elective_opted", "reg_summer_form",
                   "reg_other_form", "reg_exam_rc_form", "nep_reg_form", "cbcs_stu_course", "pre_stu_course",
                   "stu_academic", "user_details", "hm_form", "stu_section_data", "bank_fee_details",
                   "stu_fee_database_regular"],
        "text": """
<p>Every semester each student files a <b>registration form</b>: <code>reg_regular_form</code> (or <code>nep_reg_form</code> for NEP batches).
It has one row per student per <code>session_year</code> + <code>session</code> + <code>semester</code>, with approval columns <code>hod_status</code> / <code>acad_status</code>.</p>
<ul>
<li>Hanging off <code>form_id</code>: fees (<code>reg_regular_fee</code>), electives (<code>reg_regular_elective_opted</code>), chosen courses (<code>cbcs_stu_course</code>, <code>pre_stu_course</code>).</li>
<li>Other forms: summer (<code>reg_summer_form</code>), other/backlog (<code>reg_other_form</code>), exam re-check (<code>reg_exam_rc_form</code>), honours/minor (<code>hm_form</code>).</li>
<li>Sections: <code>stu_section_data</code> by <code>admn_no</code> + <code>session_year</code>.</li>
<li>Fees paid: <code>bank_fee_details</code>, matched on <code>admn_no</code> + <code>session_year</code> + <code>session</code>. Fee structure: <code>stu_fee_database_regular</code> by course, semester and category.</li>
</ul>""",
    },
    {
        "key": "results", "title": "4. Attendance, marks and results", "root": "final_semwise_marks_foil_freezed",
        "tables": ["final_semwise_marks_foil_freezed", "final_semwise_marks_foil_desc_freezed", "cbcs_transcript",
                   "reg_regular_form", "cbcs_subject_offered", "cbcs_marks_upload", "cbcs_marks_upload_description",
                   "marks_master", "subject_mapping", "cbcs_class_engaged", "cbcs_prac_group_attendance"],
        "text": """
<ul>
<li><b>Attendance:</b> classes held go in <code>class_engaged</code> / <code>cbcs_class_engaged</code> (<code>nep_class_engaged_course_wise</code> for NEP), and absences in <code>absent_table</code> / <code>cbcs_absent_table</code> / <code>nep_absent_table_course_wise</code>. Practical groups use <code>cbcs_prac_group_attendance</code>.</li>
<li><b>Marks:</b> <code>cbcs_marks_upload</code> (one upload per subject offering) with per-student rows in <code>cbcs_marks_upload_description</code> (<code>marks_id</code>). Older scheme: <code>marks_master</code> &rarr; <code>subject_mapping</code>. NEP: <code>nep_marks_upload</code> + <code>_description</code>.</li>
<li><b>Results:</b> <code>final_semwise_marks_foil_freezed</code> is the published result, one row per student per semester (GPA, CGPA, status). Subject-wise grades are in <code>final_semwise_marks_foil_desc_freezed</code> (<code>foil_id</code> &rarr; <code>id</code>). The non-<code>_freezed</code> versions are working copies; <code>_log</code> tables are audit trails.</li>
</ul>""",
    },
    {
        "key": "hr", "title": "5. Employees: leave, pay, GPF", "root": "emp_basic_details",
        "tables": ["emp_basic_details", "user_details", "designations", "emp_pay_details", "leave_all_kind_details",
                   "leave_auth_table", "acc_pay_details", "acc_gpf_master", "acc_gpf_account"],
        "text": """
<ul>
<li><b>Employee leave:</b> <code>leave_all_kind_details</code> (application, by <code>empno</code>, <code>ref_id</code>) and <code>leave_auth_table</code> (approval chain, <code>submitted_to</code> = approver's id).</li>
<li><b>Payroll:</b> <code>acc_pay_details</code> (monthly pay, <code>EMPNO</code>). GPF: <code>acc_gpf_master</code> / <code>acc_gpf_account</code>. The <code>acc_*</code> module also covers income tax, LIC and electricity deductions.</li>
<li>Watch out: <code>sleave_*</code> is <b>student</b> leave, keyed by <code>admn_no</code> (<code>sleave_application_details</code> + <code>sleave_auth_level</code>), not staff leave.</li>
</ul>""",
    },
    {
        "key": "hostel", "title": "6. Hostels", "root": "hs_hostel_details",
        "tables": ["hs_hostel_details", "hs_room_details", "hs_assigned_student_room", "hs_student_allotment_list",
                   "user_details"],
        "text": """
<p><code>hs_hostel_details</code> (hostel + block) &rarr; <code>hs_room_details</code> (<code>hostel_detail_id</code>) &rarr;
<code>hs_assigned_student_room</code> (<code>room_detail_id</code>, <code>admn_no</code>, entry/exit times). The hostel-level allotment
(before a room is assigned) is <code>hs_student_allotment_list</code> by <code>admn_no</code>.</p>""",
    },
    {
        "key": "admissions", "title": "7. Admissions (applicants, before they become students)", "root": "adm_mtech_appl_ms",
        "tables": ["adm_mtech_appl_ms", "adm_mtech_registration", "adm_mtech_reg_appl_program", "adm_mtech_fellowship",
                   "adm_mtech_doc", "adm_mtech_doc_ms", "adm_mtech_appl_selected", "adm_mtech_additional_round_choice"],
        "text": """
<p>Admissions has <b>one family of tables per programme</b>: <code>adm_mtech_*</code>, <code>adm_phd_*</code>,
<code>adm_phdef_*</code>, <code>adm_phdpt_*</code>, <code>adm_phdsd_*</code>, <code>adm_mba_*</code>, <code>adm_exmba_*</code>,
<code>adm_exmtech_*</code>, <code>adm_ma_*</code>, <code>adm_bsced_*</code>, <code>adm_thyrmtech_*</code>. All share the same shape,
keyed by the applicant's <b><code>registration_no</code></b>, which is <i>not</i> a <code>users.id</code>:</p>
<ul>
<li><code>_registration</code> (applicant account) &rarr; <code>_appl_ms</code> (application) &rarr; <code>_reg_appl_program</code> (programme choices);
<code>_qulaification</code>, <code>_work_exp</code>, <code>_address</code>, <code>_doc</code> (&rarr; <code>_doc_ms</code>), <code>_fellowship</code>.</li>
<li>Outcome: <code>_appl_selected</code>; M.Tech counselling (COAP) rounds: <code>adm_mtech_coap_*</code>, <code>adm_mtech_a_*</code>. Masters: <code>_program_ms</code>, <code>_degree_ms</code>, <code>_state_ms</code>, <code>_iit_ms</code>.</li>
<li>JEE / JAM intake: <code>adm_jee_*</code>, <code>adm_jam_*</code>. Once admitted, a student gets an admission number and rows in <code>users</code> / <code>stu_*</code>.</li>
</ul>
<p>Diagram shows the M.Tech family; the others follow the same pattern.</p>""",
    },
]


def edges_among(tables):
    s = set(tables)
    agg = {}
    for r in REL:
        a, ac = r["from"].split(".", 1)
        b, bc = r["to"].split(".", 1)
        if a in s and b in s and a != b:
            k = tuple(sorted((a, b)))
            e = agg.setdefault(k, {"a": k[0], "b": k[1], "pairs": [], "uses": 0, "fk": False})
            pair = f"{a}.{ac} = {b}.{bc}"
            if pair not in e["pairs"]:
                e["pairs"].append(pair)
            e["uses"] += r.get("uses", 0)
            e["fk"] |= r["source"] == "declared_fk"
    return list(agg.values())


def layout(root, tables, edges):
    """BFS layers from root (stronger joins first); unreachable tables go in a last column."""
    adj = collections.defaultdict(list)
    for e in edges:
        w = e["uses"] + (50 if e["fk"] else 0)
        adj[e["a"]].append((w, e["b"]))
        adj[e["b"]].append((w, e["a"]))
    layer = {root: 0}
    order = [root]
    i = 0
    while i < len(order):
        n = order[i]
        i += 1
        for _, m in sorted(adj[n], reverse=True):
            if m not in layer:
                layer[m] = layer[n] + 1
                order.append(m)
    maxl = max(layer.values()) if layer else 0
    for t in tables:
        if t not in layer:
            layer[t] = maxl + 1
            order.append(t)
    cols = collections.defaultdict(list)
    for t in order:
        cols[layer[t]].append(t)
    # Wrap very tall columns
    final, c = {}, 0
    for l in sorted(cols):
        items = cols[l]
        for k in range(0, len(items), 7):
            for j, t in enumerate(items[k:k + 7]):
                final[t] = (c, j)
            c += 1
    return final


def svg_for(domain):
    tables = [t for t in domain["tables"] if t in T]
    edges = edges_among(tables)
    pos = layout(domain["root"], tables, edges)
    bw, bh, gx, gy, pad = 232, 34, 300, 52, 16
    ncols = max(c for c, _ in pos.values()) + 1
    nrows = max(r for _, r in pos.values()) + 1
    W, H = pad * 2 + (ncols - 1) * gx + bw, pad * 2 + (nrows - 1) * gy + bh
    out = [f'<svg class="erd" viewBox="0 0 {W} {H}" style="max-width:{W}px" role="img" aria-label="{html.escape(domain["title"])} diagram">']
    maxu = max([e["uses"] for e in edges] + [1])
    for e in edges:
        (c1, r1), (c2, r2) = pos[e["a"]], pos[e["b"]]
        if (c1, r1) > (c2, r2):
            (c1, r1), (c2, r2) = (c2, r2), (c1, r1)
        x1 = pad + c1 * gx + (bw if c1 != c2 else bw)
        y1 = pad + r1 * gy + bh / 2
        x2 = pad + c2 * gx + (0 if c1 != c2 else bw)
        y2 = pad + r2 * gy + bh / 2
        if c1 == c2:
            bulge = 40 + 12 * abs(r2 - r1)
            d = f"M{x1},{y1} C{x1 + bulge},{y1} {x2 + bulge},{y2} {x2},{y2}"
        else:
            mx = (x1 + x2) / 2
            d = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
        w = 1 + 2.5 * math.log1p(e["uses"]) / math.log1p(maxu)
        tip = "\n".join(e["pairs"]) + (f"\nused {e['uses']}x in code" if e["uses"] else "") + ("\ndeclared FK" if e["fk"] else "")
        out.append(f'<path class="edge{" fk" if e["fk"] else ""}" data-a="{e["a"]}" data-b="{e["b"]}" d="{d}" '
                   f'stroke-width="{w:.1f}"><title>{html.escape(tip)}</title></path>')
    for t in tables:
        c, r = pos[t]
        x, y = pad + c * gx, pad + r * gy
        rows = T[t].get("approx_rows", 0)
        root = " root" if t == domain["root"] else ""
        out.append(f'<g class="node{root}" data-t="{t}"><rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="7"/>'
                   f'<text x="{x + 10}" y="{y + 21}">{html.escape(t)}</text>'
                   f'<text class="n" x="{x + bw - 8}" y="{y + 21}" text-anchor="end">{_short(rows)}</text>'
                   f'<title>{html.escape(t)}: ~{rows:,} rows, {len(T[t].get("columns", []))} columns</title></g>')
    out.append("</svg>")
    rows = "".join(
        f'<tr><td>{"<br>".join("<code>" + html.escape(p) + "</code>" for p in e["pairs"][:4])}</td>'
        f'<td>{"FK" if e["fk"] else ""}{" + " if e["fk"] and e["uses"] else ""}{str(e["uses"]) + "x in code" if e["uses"] else ""}</td></tr>'
        for e in sorted(edges, key=lambda e: (-e["fk"], -e["uses"])))
    return "\n".join(out), rows, edges


def _short(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def person_key_stats():
    by_col, by_mod = collections.Counter(), collections.Counter()
    for name, t in T.items():
        for k in t.get("person_keys", []):
            by_col[k.lower()] += 1
        if t.get("person_keys"):
            by_mod[t["module"]] += 1
    return by_col, by_mod


def main():
    n_tables = len(T)
    n_fk = sum(r["source"] == "declared_fk" for r in REL)
    n_code = len(REL) - n_fk
    by_col, by_mod = person_key_stats()
    n_person_tables = sum(1 for t in T.values() if t.get("person_keys"))
    hubs = sorted(T.values(), key=lambda t: -t.get("hub_score", 0))[:20]

    domain_html, md_domains = [], []
    for d in DOMAINS:
        svg, edge_rows, edges = svg_for(d)
        domain_html.append(f"""
<section id="{d['key']}"><h2>{html.escape(d['title'])}</h2>{d['text']}
<div class="diagram">{svg}</div>
<details><summary>Join conditions in this diagram ({len(edges)})</summary>
<table class="grid"><thead><tr><th>Join</th><th>Evidence</th></tr></thead><tbody>{edge_rows}</tbody></table></details>
</section>""")
        md_domains.append(f"## {d['title']}\n\n" + _html_to_md(d["text"]) + "\n\n**Joins (from FKs and code):**\n\n" +
                          "\n".join(f"- `{p}`" + (f" ({e['uses']}x)" if e["uses"] else "") + (" [FK]" if e["fk"] else "")
                                    for e in sorted(edges, key=lambda e: (-e["fk"], -e["uses"])) for p in e["pairs"][:2]))

    module_rows = "".join(
        f'<tr><td><code>{html.escape(m)}_</code></td><td>{html.escape(s["label"])}</td><td class="num">{s["table_count"]}</td>'
        f'<td>{", ".join("<code>" + html.escape(x) + "</code>" for x in s["core_tables"][:6])}</td></tr>'
        for m, s in CAT["modules"].items() if s["table_count"] >= 3)
    rel_rows = "".join(
        f'<tr><td><code>{html.escape(r["from"])}</code></td><td><code>{html.escape(r["to"])}</code></td>'
        f'<td>{"FK" if r["source"] == "declared_fk" else "code"}</td><td class="num">{r.get("uses", "")}</td></tr>'
        for r in REL)
    hub_rows = "".join(
        f'<tr><td><code>{html.escape(h["name"])}</code></td><td class="num">{h.get("approx_rows", 0):,}</td>'
        f'<td class="num">{len(h.get("joins", []))}</td><td class="num">{h.get("code_refs", 0)}</td></tr>' for h in hubs)
    key_rows = "".join(f'<tr><td><code>{html.escape(k)}</code></td><td class="num">{n}</td></tr>' for k, n in by_col.most_common(20))
    keymod_rows = "".join(f'<tr><td><code>{html.escape(k)}_</code></td><td class="num">{n}</td></tr>' for k, n in by_mod.most_common(20))

    page = TEMPLATE.format(
        db=CAT["database"], n_tables=n_tables, n_fk=n_fk, n_code=n_code, n_person=n_person_tables,
        n_modules=sum(1 for s in CAT["modules"].values() if s["table_count"] >= 3),
        toc="".join(f'<a href="#{d["key"]}">{html.escape(d["title"])}</a>' for d in DOMAINS),
        domains="".join(domain_html), module_rows=module_rows, rel_rows=rel_rows, n_rel=len(REL),
        hub_rows=hub_rows, key_rows=key_rows, keymod_rows=keymod_rows)
    open(os.path.join(HERE, "DB_RELATIONSHIPS.html"), "w").write(page)

    md = [f"# How `{CAT['database']}` fits together", "",
          f"{n_tables} tables after cleanup candidates are excluded. Relationships: {n_fk} declared foreign keys + {n_code} JOINs "
          "mined from the PHP code. Generated by `build_relationships_doc.py` (the HTML version has diagrams).", "",
          "**The one rule:** a person's id (`users.id`) is the admission number for students and the employee number for staff, "
          f"and it is the key into {n_person_tables} tables under names like " +
          ", ".join(f"`{k}`" for k, _ in by_col.most_common(8)) + ". Applicants (admissions) use `registration_no` instead.", ""]
    md += md_domains
    md += ["", "## Module directory", "", "| Prefix | What | Tables | Core tables |", "|---|---|---|---|"]
    md += [f"| `{m}_` | {s['label']} | {s['table_count']} | {', '.join('`' + x + '`' for x in s['core_tables'][:5])} |"
           for m, s in CAT["modules"].items() if s["table_count"] >= 3]
    md += ["", "Full relationship list: see `SCHEMA_MAP.md` or the HTML version."]
    open(os.path.join(HERE, "DB_RELATIONSHIPS.md"), "w").write("\n".join(md) + "\n")
    print(f"wrote DB_RELATIONSHIPS.html ({len(page) // 1024} KB) and DB_RELATIONSHIPS.md")


def _html_to_md(s):
    import re
    s = re.sub(r"<li>", "- ", s)
    s = re.sub(r"</?(ul|li|p|i)>", "\n", s)
    s = re.sub(r"<b>(.*?)</b>", r"**\1**", s)
    s = re.sub(r"<code>(.*?)</code>", r"`\1`", s)
    s = s.replace("&rarr;", "->")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIS Database Relationships</title>
<style>
:root {{ --bg:#f7f7f5; --panel:#fff; --text:#1c1c1a; --muted:#6b6b66; --border:#e3e2dd; --accent:#2f5bd3; --accent-soft:#e8eefc; --code:#f2f1ed; --edge:#9aa3b5; --fk:#2f5bd3; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161615; --panel:#1f1f1d; --text:#ecebe6; --muted:#9c9b95; --border:#33322f; --accent:#7ea2ff; --accent-soft:#24304d; --code:#2a2a27; --edge:#5d6578; --fk:#7ea2ff; }} }}
:root[data-theme="dark"] {{ --bg:#161615; --panel:#1f1f1d; --text:#ecebe6; --muted:#9c9b95; --border:#33322f; --accent:#7ea2ff; --accent-soft:#24304d; --code:#2a2a27; --edge:#5d6578; --fk:#7ea2ff; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:32px 16px 80px; }}
h1 {{ font-size:28px; margin:0 0 4px; }} h2 {{ font-size:21px; margin:48px 0 10px; padding-top:12px; border-top:1px solid var(--border); }}
.lede {{ color:var(--muted); margin:0 0 20px; }}
code {{ font:13px ui-monospace,SFMono-Regular,Menlo,monospace; background:var(--code); padding:1px 5px; border-radius:4px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:18px 0; }}
.stat {{ background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.stat b {{ display:block; font-size:24px; font-variant-numeric:tabular-nums; }} .stat span {{ color:var(--muted); font-size:13px; }}
.rule {{ background:var(--accent-soft); border-radius:10px; padding:14px 18px; margin:18px 0; }}
nav.toc {{ display:flex; flex-wrap:wrap; gap:6px 14px; font-size:14px; margin:10px 0 0; }}
nav.toc a {{ color:var(--accent); text-decoration:none; }}
.diagram {{ overflow-x:auto; background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:8px; margin:14px 0 8px; }}
svg.erd {{ display:block; width:100%; height:auto; min-width:720px; }}
svg.erd .node rect {{ fill:var(--panel); stroke:var(--border); stroke-width:1.2; }}
svg.erd .node.root rect {{ stroke:var(--accent); stroke-width:2; }}
svg.erd .node text {{ font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace; fill:var(--text); }}
svg.erd .node text.n {{ fill:var(--muted); font-size:11px; }}
svg.erd .edge {{ fill:none; stroke:var(--edge); opacity:.85; }}
svg.erd .edge.fk {{ stroke:var(--fk); }}
svg.erd.focus .edge {{ opacity:.12; }} svg.erd.focus .edge.hi {{ opacity:1; stroke:var(--accent); }}
svg.erd.focus .node {{ opacity:.35; }} svg.erd.focus .node.hi {{ opacity:1; }}
svg.erd .node {{ cursor:pointer; }}
.legend {{ font-size:13px; color:var(--muted); }}
details > summary {{ cursor:pointer; color:var(--accent); font-size:14px; margin:6px 0; }}
table.grid {{ border-collapse:collapse; width:100%; font-size:13.5px; background:var(--panel); }}
table.grid th, table.grid td {{ border-bottom:1px solid var(--border); padding:6px 10px; text-align:left; vertical-align:top; }}
table.grid th {{ font-size:12.5px; color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--panel); }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.scroll {{ max-height:520px; overflow:auto; border:1px solid var(--border); border-radius:8px; }}
input.filter {{ width:320px; max-width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px; background:var(--panel); color:var(--text); font:inherit; margin:6px 0 10px; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:720px) {{ .two {{ grid-template-columns:1fr; }} h1 {{ font-size:23px; }} }}
</style></head>
<body><main>
<h1>How the MIS database fits together</h1>
<p class="lede"><code>{db}</code>: a map of the data and how tables connect, for the RPE and DB admin teams. Built from schema metadata plus the JOINs the PHP application actually runs. No row data was read to build it.</p>
<div class="stats">
<div class="stat"><b>{n_tables:,}</b><span>tables mapped (backup/empty drop candidates excluded)</span></div>
<div class="stat"><b>{n_modules}</b><span>modules (by name prefix, 3+ tables)</span></div>
<div class="stat"><b>{n_fk}</b><span>declared foreign keys</span></div>
<div class="stat"><b>{n_code}</b><span>JOINs mined from the code</span></div>
<div class="stat"><b>{n_person}</b><span>tables that hold a person's id</span></div>
</div>
<div class="rule"><b>The one rule to remember:</b> a person's id (<code>users.id</code>) is the <b>admission number</b> for students and the
<b>employee number</b> for staff, and the same value appears in {n_person} tables under different column names
(<code>admn_no</code>, <code>emp_no</code>, <code>EMPNO</code>, <code>emp_id</code>, <code>admission_no</code>, ...).
Only 130 relationships are declared as foreign keys; everything else is enforced by the application code, which is where the other joins below come from.</div>
<nav class="toc">{toc}<a href="#hubs">Hub tables</a><a href="#personkeys">Person-id columns</a><a href="#modules">Module directory</a><a href="#all">All relationships</a></nav>
<p class="legend">Diagrams: thicker line = join used more often in the code; blue = declared foreign key. Hover a line for the exact columns; click a table to highlight its connections. Numbers on boxes are approximate row counts.</p>
{domains}
<section id="hubs"><h2>Hub tables</h2><p>The most connected tables. Most questions touch at least one of these.</p>
<table class="grid"><thead><tr><th>Table</th><th>~Rows</th><th>Known joins</th><th>Code files using it</th></tr></thead><tbody>{hub_rows}</tbody></table></section>
<section id="personkeys"><h2>Where a person's id appears</h2><p>Column names that carry <code>users.id</code>, and the modules with the most person-linked tables. The People tab uses this map to show everything about one student or employee.</p>
<div class="two"><table class="grid"><thead><tr><th>Column name</th><th>Tables</th></tr></thead><tbody>{key_rows}</tbody></table>
<table class="grid"><thead><tr><th>Module</th><th>Person-linked tables</th></tr></thead><tbody>{keymod_rows}</tbody></table></div></section>
<section id="modules"><h2>Module directory</h2>
<input class="filter" data-target="modtable" placeholder="Filter modules, e.g. fee, hostel, phd">
<div class="scroll"><table class="grid" id="modtable"><thead><tr><th>Prefix</th><th>What it is</th><th>Tables</th><th>Core tables (most connected first)</th></tr></thead><tbody>{module_rows}</tbody></table></div></section>
<section id="all"><h2>All relationships ({n_rel})</h2>
<input class="filter" data-target="reltable" placeholder="Filter, e.g. admn_no or reg_regular_form">
<div class="scroll"><table class="grid" id="reltable"><thead><tr><th>From</th><th>To</th><th>Source</th><th>Uses in code</th></tr></thead><tbody>{rel_rows}</tbody></table></div></section>
</main>
<script>
document.querySelectorAll("input.filter").forEach(inp => inp.addEventListener("input", () => {{
  const f = inp.value.toLowerCase();
  document.querySelectorAll("#" + inp.dataset.target + " tbody tr").forEach(tr => tr.hidden = f && !tr.textContent.toLowerCase().includes(f));
}}));
document.querySelectorAll("svg.erd").forEach(svg => svg.querySelectorAll(".node").forEach(n => n.addEventListener("click", () => {{
  const t = n.dataset.t, on = !(svg.classList.contains("focus") && n.classList.contains("hi"));
  svg.classList.toggle("focus", on);
  svg.querySelectorAll(".hi").forEach(x => x.classList.remove("hi"));
  if (!on) return;
  n.classList.add("hi");
  svg.querySelectorAll(".edge").forEach(e => {{
    if (e.dataset.a === t || e.dataset.b === t) {{
      e.classList.add("hi");
      svg.querySelector(`.node[data-t="${{e.dataset.a === t ? e.dataset.b : e.dataset.a}}"]`)?.classList.add("hi");
    }}
  }});
}})));
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
