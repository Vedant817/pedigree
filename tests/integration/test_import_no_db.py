"""P-025: importing the app/MCP modules must not touch FalkorDB.

Red-at-parent: `app = create_app()` ran at module import, and
`mcp_server._build_default()` created a Db + pinged at import, so
`FALKOR_PORT=1 python -c "import pedigree.api.app, pedigree.mcp_server"` died with
`RuntimeError: index creation failed ... connection refused`.
"""
from __future__ import annotations

import os
import subprocess
import sys


def test_import_has_no_db_side_effects():
    env = {**os.environ, "FALKOR_PORT": "1", "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-c", "import pedigree.api.app, pedigree.mcp_server"],
        capture_output=True, text=True, env=env, timeout=90,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "Traceback" not in (r.stderr or ""), r.stderr
