#!/usr/bin/env bash
# Start FalkorDB v4.22.1 WITHOUT Docker (Linux only; Windows uses the Docker path, ADR-001).
# The falkordblite wheel supplies redis-server; we load the pinned falkordb.so with the
# MANDATORY memory/timeout args (docs/09 section A: unlimited defaults once OOM-killed a box).
#
# Env: PORT (6379) | DATA_DIR (./data - use a distinct dir per server!) | FALKOR_SO
#      FALKOR_ARGS (defaults below are mandatory; do not blank them)
#
# [U] Unverified on the Windows dev host - first Linux run must verify MODULE LIST = 42201.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-6379}"
DATA_DIR="${DATA_DIR:-$ROOT/data}"
FALKOR_ARGS="${FALKOR_ARGS:-TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824}"

if [[ -z "$FALKOR_ARGS" ]]; then
  echo "[falkor] FALKOR_ARGS is empty - refusing to run without the mandatory limits" >&2
  exit 1
fi

# locate redis-server: PATH first, then the falkordblite package
REDIS_SERVER="${REDIS_SERVER:-}"
if [[ -z "$REDIS_SERVER" ]]; then
  if command -v redis-server >/dev/null 2>&1; then
    REDIS_SERVER="$(command -v redis-server)"
  elif python3 -c "import falkordblite" >/dev/null 2>&1; then
    REDIS_SERVER="$(python3 - <<'PY'
import pathlib, falkordblite
pkg = pathlib.Path(falkordblite.__file__).parent
for c in pkg.rglob("redis-server"):
    if c.is_file():
        print(c); break
PY
)"
  fi
fi
if [[ -z "$REDIS_SERVER" || ! -x "$REDIS_SERVER" ]]; then
  echo "[falkor] redis-server not found. Install the Python extra: pip install falkordblite==0.10.0" >&2
  echo "         (or set REDIS_SERVER=/path/to/redis-server)" >&2
  exit 1
fi

FALKOR_SO="${FALKOR_SO:-}"
if [[ -z "$FALKOR_SO" ]]; then
  CANDIDATE="$ROOT/bin/falkordb-4.22.1-x64.so"
  if [[ -f "$CANDIDATE" ]]; then
    FALKOR_SO="$CANDIDATE"
  fi
fi
if [[ -z "$FALKOR_SO" || ! -f "$FALKOR_SO" ]]; then
  echo "[falkor] pinned module not found. Run: bash scripts/fetch-falkordb.sh" >&2
  exit 1
fi

if redis-cli -p "$PORT" ping 2>/dev/null | grep -q PONG; then
  echo "[falkor] something is already answering on port $PORT"
  redis-cli -p "$PORT" MODULE LIST | head -20
  exit 0
fi

mkdir -p "$DATA_DIR"
LOG="$DATA_DIR/redis-$PORT.log"
echo "[falkor] starting redis-server $REDIS_SERVER on :$PORT (data: $DATA_DIR, log: $LOG)"
setsid nohup "$REDIS_SERVER" \
  --port "$PORT" \
  --dir "$DATA_DIR" \
  --appendonly yes --save 900 1 \
  --loadmodule "$FALKOR_SO" $FALKOR_ARGS \
  >>"$LOG" 2>&1 &

for _ in $(seq 1 60); do
  if redis-cli -p "$PORT" ping 2>/dev/null | grep -q PONG; then
    echo "[falkor] up. MODULE LIST:"
    redis-cli -p "$PORT" MODULE LIST
    exit 0
  fi
  sleep 0.5
done
echo "[falkor] server did not answer within 30s; see $LOG" >&2
exit 1
