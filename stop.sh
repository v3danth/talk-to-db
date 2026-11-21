#!/usr/bin/env bash
# Stop the background talk-to-db server started by start.sh
exec "$(dirname "${BASH_SOURCE[0]}")/start.sh" stop
