#!/usr/bin/env bash
# Verify committed HEAD in an owned Linux clone; caller owns DB startup/shutdown.
# Requires git, uv, make and Python 3.12.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pedigree-clone-XXXXXX")"
# mktemp returns the exact directory this invocation owns; never remove ROOT/data.
trap 'rm -rf -- "$TMP"' EXIT
git -C "$ROOT" rev-parse --verify HEAD >/dev/null
command -v uv >/dev/null
command -v make >/dev/null
echo "[clean-clone] cloning committed HEAD into $TMP/pedigree"
git clone --quiet --local --no-hardlinks "$ROOT" "$TMP/pedigree"
cd "$TMP/pedigree"
echo "[clean-clone] frozen Python 3.12 install"
uv sync --frozen --python 3.12 --extra dev
uv lock --check
.venv/bin/python -m pedigree.cli db status
make check
.venv/bin/python scripts/secret_scan.py --history
echo "[clean-clone] bounded perf checks (not the full scaling gate)"
.venv/bin/python -m pytest -q tests/perf/test_perf_lite.py
echo "[clean-clone] PASS"
