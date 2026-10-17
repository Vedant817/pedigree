#!/usr/bin/env bash
# Official pinned Linux x64 module. Verify content against the release API digest.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON_BIN:-python3}" "$ROOT/scripts/runtime.py" fetch
