#!/usr/bin/env bash
# Installs the locked Linux localdb extra, then owns both processes until interrupted.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v uv >/dev/null || python3 -m pip install uv==0.12.22
uv sync --frozen --extra dev --extra localdb
export PATH="$ROOT/.venv/bin:$PATH"
bash scripts/fetch-falkordb.sh
exec python scripts/runtime.py quickstart
