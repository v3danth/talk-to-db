#!/usr/bin/env bash
# Drops unwanted tables from mis_40_50, taking a mysqldump backup of exactly those tables first.
# Usage: ./drop_unwanted_tables.sh [tier1|tier2|tier3|all] [--yes]   (all = tier1+tier2; tier3 must be run explicitly)
set -euo pipefail
cd "$(dirname "$0")"
DB="${DB:-mis_40_50}"; MYSQL_USER="${MYSQL_USER:-root}"
TIER="${1:-tier1}"; CONFIRM="${2:-}"
case "$TIER" in
  tier1) FILES=(tier1_backup_and_dated_copies.sql) ;;
  tier2) FILES=(tier2_empty_unreferenced.sql) ;;
  tier3) FILES=(tier3_numbered_snapshots.sql) ;;
  all)   FILES=(tier1_backup_and_dated_copies.sql tier2_empty_unreferenced.sql) ;;
  *) echo "usage: $0 [tier1|tier2|tier3|all] [--yes]" >&2; exit 2 ;;
esac
TABLES=()
for f in "${FILES[@]}"; do
  while IFS= read -r t; do TABLES+=("$t"); done < <(grep -oE '^DROP TABLE IF EXISTS `[^`]+`' "$f" | sed -E 's/.*`([^`]+)`/\1/')
done
echo "Will drop ${#TABLES[@]} tables from $DB (${FILES[*]})."
if [[ "$CONFIRM" != "--yes" ]]; then read -r -p "Type DROP to continue: " ans; [[ "$ans" == "DROP" ]] || { echo "Aborted."; exit 1; }; fi
mkdir -p backups
BK="backups/${DB}_${TIER}_$(date +%Y%m%d_%H%M%S).sql.gz"
echo "Backing up to $BK ..."
mysqldump -u"$MYSQL_USER" --single-transaction --skip-triggers --set-gtid-purged=OFF "$DB" "${TABLES[@]}" | gzip > "$BK"
gzip -t "$BK"
echo "Backup OK ($(du -h "$BK" | cut -f1)). Dropping..."
for f in "${FILES[@]}"; do mysql -u"$MYSQL_USER" "$DB" < "$f"; done
echo "Done. Restore with: gunzip -c $BK | mysql -u$MYSQL_USER $DB"
