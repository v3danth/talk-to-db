#!/usr/bin/env bash
# Start talk-to-db in the background behind hop, at http://ttd/
#   ./start.sh          start (no-op if already running)
#   ./start.sh stop     stop it
#   ./start.sh status   show whether it's running
#   ./start.sh logs     follow the server log
set -euo pipefail

NAME="${HOP_APP_NAME:-ttd}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
LOG_FILE="$LOG_DIR/server.log"
VENV="$DIR/venv"
[ -x "$VENV/bin/uvicorn" ] || VENV="$DIR/.venv"

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

case "${1:-start}" in
  start)
    if running; then echo "already running (pid $(cat "$PID_FILE")) at http://$NAME/"; exit 0; fi
    mkdir -p "$LOG_DIR"
    cd "$DIR"
    # hop picks a free port, passes it as $PORT, and maps http://$NAME/ to it while the app runs.
    nohup setsid hop run "$NAME" -- bash -c \
      "exec '$VENV/bin/uvicorn' app:app --host 127.0.0.1 --port \"\$PORT\"" \
      >>"$LOG_FILE" 2>&1 </dev/null &
    echo $! >"$PID_FILE"
    sleep 2
    if running; then echo "started (pid $(cat "$PID_FILE")) at http://$NAME/  - log: $LOG_FILE"
    else echo "failed to start; last log lines:"; tail -n 20 "$LOG_FILE"; rm -f "$PID_FILE"; exit 1; fi
    ;;
  stop)
    if running; then
      kill -- -"$(cat "$PID_FILE")" 2>/dev/null || kill "$(cat "$PID_FILE")"
      rm -f "$PID_FILE"; echo "stopped"
    else rm -f "$PID_FILE"; echo "not running"; fi
    ;;
  status)
    if running; then echo "running (pid $(cat "$PID_FILE")) at http://$NAME/"; else echo "not running"; fi
    ;;
  logs) tail -f "$LOG_FILE" ;;
  *) echo "usage: $0 [start|stop|status|logs]"; exit 1 ;;
esac
