#!/usr/bin/env bash
# Thin wrapper referenced by docs/00 (Step 7) and the final checklist.
# Scans tracked files AND full git history; exits non-zero on any finding.
# Works from Git bash/WSL on Windows and from plain Linux (the scanner needs only
# python3 + git - it does not import the pedigree package).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  MINGW*|MSYS*|CYGWIN*|Windows*)
    PY="$ROOT/.venv/Scripts/python.exe" ;;
  *)
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
      PY="$ROOT/.venv/bin/python"
    else
      PY="python3"
    fi ;;
esac
exec "$PY" "$ROOT/scripts/secret_scan.py" --history "$@"
