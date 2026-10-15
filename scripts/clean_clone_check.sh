#!/usr/bin/env bash
# AT0.6 / AT4.2: prove that a FRESH CLONE of the committed repository builds and passes.
# Clones the local repo's committed state (not the working tree), then runs setup, the
# full test suite and the cheap checks - exactly what a judge would do from the README.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pedigree-clone-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "[clean-clone] repo:  $ROOT"
echo "[clean-clone] clone: $TMP/pedigree"
if ! git -C "$ROOT" rev-parse --verify -q HEAD >/dev/null; then
  echo "[clean-clone] FAIL: no commits in $ROOT - nothing a judge could clone" >&2
  exit 1
fi
git clone --quiet --local "$ROOT" "$TMP/pedigree"
cd "$TMP/pedigree"

echo "[clean-clone] make setup"
make setup

echo "[clean-clone] database check"
if ! make db-status; then
  echo "[clean-clone] FAIL: FalkorDB not reachable - start it first (make start-db)" >&2
  exit 1
fi

echo "[clean-clone] make test"
make test

echo "[clean-clone] make check"
make check

echo "[clean-clone] PASS"
