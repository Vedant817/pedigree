#!/usr/bin/env bash
# Downloads the official FalkorDB v4.22.1 module (51 MB) next to this script. Not shipped in the pack (binary).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; mkdir -p "$HERE/bin"
URL="https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.1/falkordb-x64.so"
curl -fL --retry 3 -o "$HERE/bin/falkordb-4.22.1-x64.so" "$URL"
chmod +x "$HERE/bin/falkordb-4.22.1-x64.so"      # forgetting this => "does not have execute permissions", server aborts
ls -l "$HERE/bin/falkordb-4.22.1-x64.so"
