#!/usr/bin/env bash
# Safe nightly copy of the orders database. Keeps the last 30 copies.
# Usage: backup.sh [destination folder]   (default /opt/karam-kitchen/backups; use a USB drive path if you have one)
set -euo pipefail
APP=/opt/karam-kitchen
DEST="${1:-$APP/backups}"
mkdir -p "$DEST"
OUT="$DEST/orders-$(date +%Y%m%d-%H%M).db"
"$APP/.venv/bin/python" - "$APP/data/orders.db" "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
chmod 600 "$OUT"
ls -1t "$DEST"/orders-*.db | tail -n +31 | xargs -r rm --
echo "backup written: $OUT"
