#!/usr/bin/env bash
# Stop the no-Docker FalkorDB started by scripts/start-falkordb.sh (docs/09 process hygiene).
set -euo pipefail

PORT="${PORT:-6379}"

if redis-cli -p "$PORT" ping 2>/dev/null | grep -q PONG; then
  echo "[falkor] shutting down redis-server on :$PORT"
  redis-cli -p "$PORT" shutdown nosave 2>/dev/null || true
  for _ in $(seq 1 40); do
    if ! redis-cli -p "$PORT" ping 2>/dev/null | grep -q PONG; then
      echo "[falkor] stopped"
      exit 0
    fi
    sleep 0.25
  done
  echo "[falkor] still answering; falling back to pkill"
fi

if pkill -f "redis-server .*--port $PORT" 2>/dev/null; then
  echo "[falkor] killed by pattern"
else
  echo "[falkor] nothing to stop on port $PORT"
fi
