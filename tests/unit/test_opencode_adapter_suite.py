"""Runs the F-08 OpenCode adapter's builtin Node regression suite under pytest.

The adapter is dependency-free Node ESM (``adapters/opencode``): fixture mapping,
hook behaviour, path containment, privacy canaries and bounds/configuration. The
suites only use ``node:test``/``node:assert``. This wrapper keeps ``make check``
and ``make test`` from silently skipping them; QA reruns them independently.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "adapters" / "opencode" / "tests"
SUITES = [
    "fixture-mapping.test.js",
    "hooks.test.js",
    "paths.test.js",
    "privacy.test.js",
    "bounds-config.test.js",
    "native-tools.test.js",
]

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node runtime is not installed")
def test_opencode_adapter_node_suite() -> None:
    assert NODE is not None
    process = subprocess.run(
        [NODE, "--test", *[str(TESTS / name) for name in SUITES]],
        capture_output=True,
        cwd=str(REPO),
        timeout=300,
    )
    stdout = process.stdout.decode("utf-8", "replace")
    stderr = process.stderr.decode("utf-8", "replace")
    assert process.returncode == 0, f"node adapter suite failed:\n{stdout}\n{stderr}"
    assert "fail 0" in stdout, stdout
