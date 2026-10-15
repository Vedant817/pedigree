#!/usr/bin/env bash
# AT0.6 / AT4.2: prove that a FRESH CLONE of the committed repository builds and passes
# with nothing but system python3 + pip (no make, no uv, no Docker required for the check
# itself). Run from the repo root on Linux/WSL: bash scripts/clean_clone_check.sh
set -euo pipefail

PYTHON="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pedigree-clone-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "[clean-clone] repo:  $ROOT"
echo "[clean-clone] clone: $TMP/pedigree"
if ! git -C "$ROOT" rev-parse --verify -q HEAD >/dev/null; then
  echo "[clean-clone] FAIL: no commits in $ROOT - nothing a judge could clone" >&2
  exit 1
fi
# --no-hardlinks: /tmp is a different filesystem than the repo on WSL/Windows mounts
git clone --quiet --local --no-hardlinks "$ROOT" "$TMP/pedigree"
cd "$TMP/pedigree"

echo "[clean-clone] venv + install"
UV=""
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV="$HOME/.local/bin/uv"
fi
if [[ -n "$UV" ]]; then
  echo "[clean-clone] using uv ($UV)"
  "$UV" venv --python "${PYTHON_VERSION:-3.12}" .venv
  "$UV" pip install --python .venv/bin/python -e ".[dev]"
  PY=.venv/bin/python
else
  echo "[clean-clone] using $PYTHON -m venv"
  if ! "$PYTHON" -m venv .venv; then
    echo "[clean-clone] FAIL: cannot create a venv. Install python3-venv (Debian/Ubuntu:" >&2
    echo "              apt install python3.12-venv) or install uv (https://astral.sh/uv)" >&2
    exit 1
  fi
  PY=.venv/bin/python
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -e ".[dev]"
fi

echo "[clean-clone] database check"
if ! "$PY" -m pedigree.cli db status; then
  echo "[clean-clone] FAIL: FalkorDB not reachable from here - start it first (make start-db)" >&2
  exit 1
fi

echo "[clean-clone] lint"
"$PY" -m ruff check .

echo "[clean-clone] tests"
"$PY" -m pytest -q

echo "[clean-clone] secret scan + numbers"
"$PY" scripts/secret_scan.py
"$PY" scripts/check_numbers.py

echo "[clean-clone] PASS"
