#!/usr/bin/env bash
# No port-based shutdown or process-pattern kill: stop the foreground owner's PID.
set -euo pipefail
echo "Stop the owning quickstart process with Ctrl-C; this script never stops an arbitrary listener." >&2
exit 1
