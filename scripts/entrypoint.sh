#!/usr/bin/env bash
# API only: Compose owns the separate database process.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python scripts/runtime.py wait-db
if [[ "${PEDIGREE_SEED_DEMO:-0}" == "1" ]]; then
  python scripts/seed_demo.py
fi
exec python -m uvicorn pedigree.api.app:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers
