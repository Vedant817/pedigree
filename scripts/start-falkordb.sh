#!/usr/bin/env bash
# Foreground only. The caller owns this exact process and its termination.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON_BIN:-python3}" "$ROOT/scripts/runtime.py" db
