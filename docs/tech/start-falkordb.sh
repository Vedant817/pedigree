#!/usr/bin/env bash
# Starts a real FalkorDB (redis-server from the falkordblite wheel + a FalkorDB .so) WITHOUT Docker.
# Env: PORT (6379) | DATA_DIR (default ./data next to this script; NEVER share one DATA_DIR between two servers)
#      FALKOR_SO (default: bin/falkordb-4.22.1-x64.so if present, else the wheel's bundled 4.18.3 .so)
#      FALKOR_ARGS (default: TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824 = MANDATORY, see GOTCHAS #1)
# Setup once: bash setup.sh   (creates .venv, installs falkordblite+falkordb+mcp, fetches the pinned .so)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${VENV:-$HERE/.venv}"
SP=$(ls -d "$VENV"/lib/python3*/site-packages/redislite/bin 2>/dev/null | head -1 || true)
if [ -z "$SP" ]; then echo "redis-server not found: run 'bash $HERE/setup.sh' first (or set VENV=/path/to/venv with falkordblite installed)" >&2; exit 1; fi
DATA_DIR="${DATA_DIR:-$HERE/data}"; mkdir -p "$DATA_DIR"
if [ -z "${FALKOR_SO:-}" ]; then
  if [ -f "$HERE/bin/falkordb-4.22.1-x64.so" ]; then FALKOR_SO="$HERE/bin/falkordb-4.22.1-x64.so"; else FALKOR_SO="$SP/falkordb.so"; echo "WARNING: pinned 4.22.1 .so not found, using bundled one (4.18.3)" >&2; fi
fi
[ -x "$FALKOR_SO" ] || { echo "$FALKOR_SO is not executable: chmod +x it" >&2; exit 1; }
exec "$SP/redis-server" --port "${PORT:-6379}" --bind 127.0.0.1 --dir "$DATA_DIR" \
  --loadmodule "$FALKOR_SO" ${FALKOR_ARGS:-TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824} \
  --save "60 1000" --appendonly yes --daemonize no
