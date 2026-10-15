#!/usr/bin/env bash
# One-time setup of the FalkorDB runtime for local development (no Docker). Needs python3 >= 3.11, curl, glibc >= 2.39 (Ubuntu 24.04+/Debian 13+).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install --quiet --upgrade pip
"$HERE/.venv/bin/pip" install --quiet "falkordblite==0.10.0" "falkordb==1.8.0" "mcp>=2,<3"      # ~160 MB venv; wheel ships redis-server 8.6.2
bash "$HERE/fetch-falkordb.sh"
chmod +x "$HERE/start-falkordb.sh"
echo "Next: PORT=6379 DATA_DIR=\$PWD/data ./start-falkordb.sh &   then   FALKOR_PORT=6379 $HERE/.venv/bin/python $HERE/examples/py/12_pedigree_core.py"
