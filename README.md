# Talk to MIS DB

Three tools for the RPE / DB admin team, all at http://127.0.0.1:8765:

- **People** (no API key needed): search students, faculty and staff with `name=ravi kumar type=student dept=cse`,
  `phone=98765`, `email=...`, `id=21je`, `designation=professor`, 39 fields in all (address, city, hostel, category,
  blood, level, via, joined, research, ...; click **Fields** in the UI for the full list). Click a person for their full profile and
  everything linked to them across ~690 tables, grouped by module. Large unindexed tables have on-demand Scan buttons.
  Passwords/hashes/OTPs are never shown; Aadhaar/bank/PAN/passport are masked until "Show masked fields" is ticked.
  Every search, profile view and reveal is logged to `logs/people_access.log`.
- **Relationships** (`/relationships`, also `DB_RELATIONSHIPS.html` / `.md`): how the database fits together, with diagrams.
- **Ask (AI)** (needs `ANTHROPIC_API_KEY`): ask questions about `mis_40_50` in plain English. Claude searches the schema map, writes SQL, runs it on a
**read-only** MySQL account, and shows every query and result table (copy SQL / download CSV).

## Run

```bash
cd ~/Projects/talk_to_db
export ANTHROPIC_API_KEY=sk-ant-...        # Claude API key
mysql -uroot < setup_readonly_user.sql     # once: creates talk_to_db_ro (SELECT only) - already done locally
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

Fresh machine: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`. `build_catalog.py` reads the PHP code from `~/Projects/MIS_code/application` (override with `MIS_CODE_DIR`).
Settings (DB host, users, model, row caps, timeout) are environment variables - see `config.py`.

## Files

| File | What |
|---|---|
| `build_catalog.py` | Builds the schema map from `information_schema` + JOINs mined from the MIS PHP code (`~/Projects/MIS_code/application`). Re-run after schema changes or cleanup. |
| `catalog.json` | The map the agent uses (tables, columns, joins, modules, code usage). |
| `SCHEMA_MAP.md` | Human-readable map: modules, hub tables, strongest join paths, declared FKs. |
| `knowledge.md` | Business rules fed to the agent. Add a line whenever it gets something wrong. |
| `people.py` | People search, profile, linked-data scan, masking, audit log. |
| `build_relationships_doc.py` | Generates `DB_RELATIONSHIPS.html` + `.md` from the catalog. Re-run after `build_catalog.py`. |
| `agent.py` | Tools (`search_tables`, `describe_tables`, `run_sql`) and the Claude tool loop. |
| `app.py`, `static/index.html` | Web server (streams progress) and UI (Ask + Schema map tabs). |
| `cleanup/` | Scripts to drop unwanted tables (see below). |

## Safety

- Queries run as `talk_to_db_ro` (SELECT + SHOW VIEW only) inside a `READ ONLY` transaction, with
  `max_execution_time` 30 s. `sqlglot` also rejects anything that is not a single SELECT.
- Results go to the Claude API so it can answer: up to 50 rows per query, values clipped to 200 chars.
  Don't expose this server beyond localhost without adding auth.

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
