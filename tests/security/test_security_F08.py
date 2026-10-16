"""F-08 OpenCode adapter security regressions (red-team findings as permanent tests).

Companion to ``docs/qa/redteam-F-08.md``. Covers:

1. Windows alternate-stream and drive-relative path forms (``id_rsa::$DATA``,
   ``C:file``, ``file:stream``) are denied in the real plugin entry before any
   transport runs. A silent listening socket proves zero connection attempts,
   and an in-project control read proves the oracle distinguishes the path
   stage (``path_stream``) from the transport stage (``endpoint_unavailable``).
2. The gate's session read window is exactly the documented last-K influence
   window (``pedigree_read_window``, default 50): with 50 newer reads, a
   revoked source is evicted and no longer consulted. That bound is disclosed,
   not silent - a strict xfail watchdog asserts the stronger property and turns
   into a failure the moment the semantics become eviction-proof.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from pedigree.engine.gate import check_action
from pedigree.engine.ingest import ensure_session, read_window, record_source, session_read
from pedigree.engine.revoke import revoke

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "adapters" / "opencode" / "tests" / "driver.js"

NODE = shutil.which("node")
WIN32 = sys.platform == "win32"

pytestmark = pytest.mark.skipif(NODE is None, reason="node runtime is not installed")

DENIED_STREAM_MESSAGE = (
    "pedigree: read denied; drive-relative and alternate-stream path forms are not supported"
)
UNAVAILABLE_MESSAGE = "pedigree: read denied; Pedigree endpoint is unavailable"


def _run_driver(job: dict, *, base: str, tmp_path: Path, name: str) -> list[dict]:
    """Run one job through the real plugin entry; return per-hook results."""
    job_path = tmp_path / f"job-sec-{name}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    env = {
        **os.environ,
        "PEDIGREE_OPENCODE_ENABLED": "1",
        "PEDIGREE_OPENCODE_URL": base,
        "PEDIGREE_OPENCODE_TOKEN": "unused-token",
    }
    process = subprocess.run(
        [NODE, str(DRIVER), str(job_path)],
        capture_output=True,
        cwd=str(REPO),
        env=env,
        timeout=60,
    )
    stdout = process.stdout.decode("utf-8", "replace")
    stderr = process.stderr.decode("utf-8", "replace")
    assert process.returncode == 0, f"driver failed:\n{stdout}\n{stderr}"
    assert stderr == "", f"unexpected adapter stderr: {stderr}"
    return json.loads(stdout)["results"]


def _before_hook(session_id: str, call_id: str, file_path: str) -> dict:
    return {
        "phase": "before",
        "input": {"tool": "read", "sessionID": session_id, "callID": call_id},
        "output": {"args": {"filePath": file_path}},
    }


@pytest.mark.skipif(not WIN32, reason="NTFS stream and drive-relative grammar is Windows-only")
def test_win32_stream_and_drive_relative_paths_are_denied_with_zero_network(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "dummy.txt").write_text("Synthetic security sink.\n", encoding="utf-8")
    (project / "id_rsa").write_text("stream canary bytes\n", encoding="utf-8")

    # A silent listener: anything the adapter dials would queue here, proof of a
    # connection attempt or of none.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    try:
        port = listener.getsockname()[1]
        candidates = [
            "dummy.txt::$DATA",
            "id_rsa::$DATA",
            str(project / "dummy.txt") + ":stream",
            "C:dummy.txt",
        ]
        hooks = [
            _before_hook("ses_sec_stream", f"call_sec_{index}", candidate)
            for index, candidate in enumerate(candidates)
        ]
        results = _run_driver(
            {"project": str(project), "hooks": hooks},
            base=f"http://127.0.0.1:{port}",
            tmp_path=tmp_path,
            name="streams",
        )
        assert results == [
            {"ok": False, "code": "path_stream", "message": DENIED_STREAM_MESSAGE}
            for _ in candidates
        ], results
        ready, _, _ = select.select([listener], [], [], 0.0)
        assert ready == [], "a denied path form must not cause any network connection"

        # Control: the same plumbing with an allowed path does reach transport and
        # fails there (closed port), so the denial above is the path stage, not a
        # broken harness.
        control = _run_driver(
            {"project": str(project), "hooks": [_before_hook("ses_sec_stream", "call_sec_ok", str(project / "dummy.txt"))]},
            base="http://127.0.0.1:9",
            tmp_path=tmp_path,
            name="control",
        )
        assert control == [
            {"ok": False, "code": "endpoint_unavailable", "message": UNAVAILABLE_MESSAGE}
        ], control
    finally:
        listener.close()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "pedigree_read_window is the documented bounded last-K influence window (default 50); "
        "a revoked source evicted by 50 newer reads is no longer consulted. This watchdog asserts "
        "the stronger, eviction-proof property and flips when that semantics changes."
    ),
)
def test_gate_still_blocks_revoked_source_after_read_window_eviction(fresh_graph):
    db, tenant, graph = fresh_graph
    sid = "ses_sec_window"
    ensure_session(db, graph, tenant, sid, runtime="opencode")

    victim_id = "src_sec_window_victim"
    record_source(db, graph, tenant, id=victim_id, kind="file", uri="readview:v1/sec/window.txt")
    session_read(db, graph, sid, victim_id, now=1_000)
    revoke(db, graph, tenant, root_id=victim_id)

    for index in range(51):
        filler_id = f"src_sec_window_fill_{index:02d}"
        record_source(db, graph, tenant, id=filler_id, kind="file", uri=f"readview:v1/sec/fill-{index:02d}.txt")
        session_read(db, graph, sid, filler_id, now=2_000 + index)

    assert victim_id not in read_window(db, graph, sid, 50), (
        "premise: 50 newer reads evict the revoked source from the documented window"
    )
    decision = check_action(
        db,
        graph,
        {"tool": "read", "summary": "read window.txt", "effect": "reversible", "risk": "low"},
        session_id=sid,
    )
    assert decision["decision"] in {"reverify", "block"}, (
        "a read that the session previously captured from a now-revoked source must not become "
        f"silently allowed after churn; got {decision['decision']!r} "
        f"(checked {decision['checked']} window entries)"
    )
