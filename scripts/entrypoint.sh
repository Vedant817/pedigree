#!/usr/bin/env bash
# Single-container entrypoint: FalkorDB v4.22.1 (pinned .so, no Docker-in-Docker) + the
# Pedigree service (REST + MCP + static UI). Used by the Dockerfile (F-16) locally and on
# Render; the human-facing instructions are in README "Deploy".
#
# Order: fetch/verify the pinned module -> start the server -> wait until it answers ->
# optionally seed the demo tenant on boot -> exec the API service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON_BIN:-python3}"
PORT="${PORT:-${FALKOR_PORT:-6379}}"
DATA_DIR="${DATA_DIR:-$ROOT/data}"

echo "[entrypoint] fetching/verifying the pinned FalkorDB module"
bash scripts/fetch-falkordb.sh

echo "[entrypoint] starting FalkorDB on port $PORT (data: $DATA_DIR)"
mkdir -p "$DATA_DIR"
PORT="$PORT" DATA_DIR="$DATA_DIR" bash scripts/start-falkordb.sh &
FALKOR_PID=$!
trap 'echo "[entrypoint] stopping FalkorDB"; kill "$FALKOR_PID" 2>/dev/null || true' EXIT INT TERM

echo "[entrypoint] waiting for FalkorDB to answer"
for _ in $(seq 1 60); do
  if "$PY" -m pedigree.cli db status >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! "$PY" -m pedigree.cli db status; then
  echo "[entrypoint] FalkorDB did not become reachable" >&2
  exit 1
fi

if [[ "${PEDIGREE_SEED_DEMO:-0}" == "1" ]]; then
  echo "[entrypoint] seeding the demo tenant (PEDIGREE_SEED_DEMO=1)"
  "$PY" scripts/seed_demo.py || echo "[entrypoint] demo seeding failed (continuing)"
fi

echo "[entrypoint] starting the Pedigree service on 0.0.0.0:${PEDIGREE_PORT:-8000}"
exec "$PY" -m pedigree.cli serve --host 0.0.0.0 --port "${PEDIGREE_PORT:-8000}"
