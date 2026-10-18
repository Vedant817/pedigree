#!/bin/sh
# Deploy-only entrypoint for the pinned FalkorDB image.
#
# Why this wrapper exists: Render private services inject $PORT and require the
# process to bind it. The upstream image's entrypoint (/var/lib/falkordb/bin/run.sh)
# always starts redis-server on 6379 and never reads $PORT, so a private service
# built straight from that image would never become reachable inside the Render
# network. Everything else - the pinned image, the module path, the query limits -
# is unchanged.
set -eu

DATA_PATH="${FALKORDB_DATA_PATH:-/var/lib/falkordb/data}"
BIN_PATH="${FALKORDB_BIN_PATH:-/var/lib/falkordb/bin}"

mkdir -p "$DATA_PATH"

if [ -n "${FALKOR_PASSWORD:-}" ]; then
    set -- --requirepass "$FALKOR_PASSWORD"
else
    set --
fi

# REDIS_ARGS and FALKORDB_ARGS are intentionally unquoted: the upstream image
# relies on word splitting to pass multiple flags through them.
# shellcheck disable=SC2086
exec redis-server "$@" ${REDIS_ARGS:-} \
    --protected-mode no \
    --port "${PORT:-6379}" \
    --dir "$DATA_PATH" \
    --loadmodule "$BIN_PATH/falkordb.so" \
    ${FALKORDB_ARGS:-}
