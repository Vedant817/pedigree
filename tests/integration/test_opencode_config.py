"""P-016: opencode.json advertises a URL that must actually answer MCP initialize."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from mcp import Client

from pedigree.db.client import Db

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:8000/mcp"


def test_opencode_json_points_at_documented_default() -> None:
    cfg = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["pedigree"]["url"] == DEFAULT_URL


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_http(url: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as c:
                if c.get(url).status_code == 200:
                    return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"server at {url} did not become ready")


def test_advertised_url_answers_mcp_initialize(db: Db) -> None:
    if not _port_free(8000):
        pytest.skip(
            "port 8000 is busy locally; the /mcp mount itself is covered by "
            "test_mcp_http_mount.py and the URL contract by the test above"
        )
    log = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".log")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app",
         "--factory", "--host", "127.0.0.1", "--port", "8000"],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT),
    )
    try:
        _wait_http("http://127.0.0.1:8000/healthz")

        async def journey() -> list[str]:
            async with Client(DEFAULT_URL) as client:
                tools = await client.list_tools()
                return [t.name for t in tools.tools]

        try:
            names = asyncio.run(journey())
        except Exception as exc:
            log.flush()
            with open(log.name, encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-2000:]
            raise AssertionError(f"opencode.json URL failed; server log tail:\n{tail}") from exc
        assert "pedigree_health" in names, names
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        log.close()
        try:
            os.unlink(log.name)
        except OSError:
            # Windows can keep the handle briefly after terminate(); harmless temp file.
            pass
