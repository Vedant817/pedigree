#!/usr/bin/env bash
# Fetch the pinned FalkorDB module for the no-Docker Linux path (docs/09 section A).
# The Docker image (primary path, ADR-001) already contains this module; this script is
# only needed when Docker is unavailable. bin/ is git-ignored. Never use `latest`.
#
# Verified command shape (docs/09, [V] on the research box):
#   curl -L -o bin/falkordb-4.22.1-x64.so https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.1/falkordb-x64.so
set -euo pipefail

VERSION="${FALKORDB_VERSION:-4.22.1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin"
SO="$BIN/falkordb-${VERSION}-x64.so"
URL="https://github.com/FalkorDB/FalkorDB/releases/download/v${VERSION}/falkordb-x64.so"

mkdir -p "$BIN"
if [[ -f "$SO" ]]; then
  echo "[fetch-falkordb] already present: $SO ($(wc -c <"$SO") bytes)"
else
  echo "[fetch-falkordb] downloading $URL"
  curl -fL --retry 3 -o "$SO" "$URL"
fi
chmod +x "$SO"  # forgetting chmod makes the server abort on load (docs/09)
sha256sum "$SO" | tee "$SO.sha256"
echo "[fetch-falkordb] done. Start with:"
echo "  FALKOR_SO=$SO PORT=6379 DATA_DIR=./data bash scripts/start-falkordb.sh"
