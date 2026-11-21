# Talk to MIS DB

Tools for the RPE / DB admin team, all at http://127.0.0.1:8765:

- **People** (no API key needed): search students, faculty and staff with `name=ravi kumar type=student dept=cse`,
  `phone=98765`, `email=...`, `id=21je`, `designation=professor`, 38 fields in all (address, city, state, branch, category,
  blood, level, via, joined, research, ...; click **Fields** in the UI for the full list). Click a person for their full profile and
  everything linked to them across ~690 tables, grouped by module. Large unindexed tables have on-demand Scan buttons.
  Passwords/hashes/OTPs are never shown; Aadhaar/bank/PAN/passport are masked until "Show masked fields" is ticked.
  Every search, profile view and reveal is logged to `logs/people_access.log`.
- **Relationships** (`/relationships`, also `DB_RELATIONSHIPS.html` / `.md`): how the database fits together, with diagrams.

## Run

```bash
cd ~/Projects/talk_to_db
mysql -uroot < setup_readonly_user.sql     # once: creates talk_to_db_ro (SELECT only) - already done locally
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

Fresh machine: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`. `build_catalog.py` reads the PHP code from `~/Projects/MIS_code/application` (override with `MIS_CODE_DIR`).
Settings (DB host, users, timeout) are environment variables - see `config.py`.

## Files

| File | What |
|---|---|
| `build_catalog.py` | Builds the schema map from `information_schema` + JOINs mined from the MIS PHP code (`~/Projects/MIS_code/application`). Re-run after schema changes or cleanup. |
| `catalog.json` | The schema map behind the Schema view (tables, columns, joins, modules, code usage). |
| `SCHEMA_MAP.md` | Human-readable map: modules, hub tables, strongest join paths, declared FKs. |
| `knowledge.md` | Domain notes and business rules about the MIS data (was fed to the removed Ask AI feature; kept for reference). |
| `people.py` | People search, value suggestions, status labels, profile, linked-data scan, masking, audit log. |
| `auth.py`, `manage_users.py` | Optional sign-in (accounts, sessions, lockout) and the CLI to manage accounts. |
| `build_relationships_doc.py` | Generates `DB_RELATIONSHIPS.html` + `.md` from the catalog. Re-run after `build_catalog.py`. |
| `schema.py` | Schema map search and table details (`search_tables`, `describe_tables`) for the Schema view. |
| `app.py`, `static/index.html`, `static/login.html` | Web server and UI (People, Schema), sign-in page. |
| `cleanup/` | Scripts to drop unwanted tables (see below). |

## Sign-in

Off by default (the header shows **⚠ No sign-in**, meaning keep it on localhost). Turn it on by adding the first account:

```bash
.venv/bin/python manage_users.py add asha "Asha Verma"   # prompts for a password (10+ chars)
.venv/bin/python manage_users.py list
.venv/bin/python manage_users.py remove asha
```

Accounts live in `users.json` (git-ignored, mode 600, PBKDF2 hashes). With sign-in on, every page and API call needs a
session (8 h, HttpOnly cookie), the audit log records `username@ip`, and 5 failed sign-ins from one address lock it out
for 5 minutes. No restart needed.

## Using People

- Type a field and `=`; suggestions show field names, then real values with counts (departments, branches, categories,
  cities, states, designations...). `Tab` completes, `↑` `↓` + `Enter` picks.
- The search lives in the URL (`#q=...`), so Back, reload and shared links restore it.
- On a profile: `J` / `K` next / previous result, `C` copies the ID, `Esc` back to results. `?` lists all shortcuts.
- Status codes are labelled: A active, P passed out, L left, I not yet reported, D deactivated; R "retired?" and
  X "ex-employee?" are inferred (never set in the PHP code).

## Safety

- Queries run as `talk_to_db_ro` (SELECT + SHOW VIEW only) inside a `READ ONLY` transaction, with
  `max_execution_time` 30 s.
- Don't expose this server beyond localhost without adding auth.

## Cleanup (`cleanup/`)

The cleanup scripts read only metadata, code references and `COUNT(*)`, never row contents.

| Tier | File | Tables | Size | Rule |
|---|---|---|---|---|
| 1 | `tier1_backup_and_dated_copies.sql` | 235 | ~1.3 GB | Backup / dated / copy / temp / test names, referenced nowhere in the PHP code |
| 2 | `tier2_empty_unreferenced.sql` | 122 | ~3 MB | Exactly 0 rows (verified), not referenced; NEP/TMS/app/HC/stock families excluded |
| 3 | `tier3_numbered_snapshots.sql` | 39 | ~75 MB | `<live_table>_<digits>` snapshots, not referenced (includes nep_* - review first) |
| - | `review_not_dropped.tsv` | 421 | ~2.3 GB | Not in PHP code but has data or looks owned by the NEP/Node app. **Not dropped.** |

```bash
cd cleanup
./drop_unwanted_tables.sh tier1     # backs up exactly those tables to backups/*.sql.gz, then drops
./drop_unwanted_tables.sh all       # tier1 + tier2
./drop_unwanted_tables.sh tier3     # only after reviewing
# restore: gunzip -c backups/<file>.sql.gz | mysql -uroot mis_40_50
```

After dropping, re-run `.venv/bin/python build_catalog.py`.

Caveat: "unreferenced" means unreferenced by the MIS PHP code only. Some tables (`nep_*`, `tms_*`, `APIRequestLog`,
`personal_access_tokens`, `sequelizemeta`) belong to a second app whose code isn't here. Those were kept out of
tiers 1-2. If that app or any cron job uses a dated/backup table directly, restore it from the backup.
