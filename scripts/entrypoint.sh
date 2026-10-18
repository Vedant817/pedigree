#!/usr/bin/env bash
# API only: Compose owns the separate database process.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python scripts/runtime.py validate-config
python scripts/runtime.py wait-db
if [[ "${PEDIGREE_SEED_DEMO:-0}" == "1" ]]; then
  python scripts/seed_demo.py
fi
# Honour $PORT when the platform injects one (Render, Heroku and similar route
# traffic to $PORT), and keep 8000 everywhere else so Compose and the local
# instructions are unaffected.
exec python -m uvicorn pedigree.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --no-proxy-headers
