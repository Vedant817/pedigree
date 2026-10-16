"""F-08 OpenCode adapter end-to-end: genuine hook replay into a live Pedigree API.

Drives recorded OpenCode 1.19.0 hook payloads
(docs/consults/opencode-recheck-2026-10-16-shape.json) through the adapter's real
plugin entry in a Node subprocess, over a real HTTP socket, into the real FastAPI
app and a real FalkorDB 4.22.1 graph. This is a *hook replay* of a genuine capture,
not an installed OpenCode session.

Asserted here: persisted Source identity (uri + independently recomputed
canonical digest), untrusted integrity on the agent channel, Session runtime and
read window, gate denial after revoking the captured source, per-tenant
isolation of identical captures, and (on Windows) case-variant paths converging
on one Source.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.engine.ingest import read_window
from pedigree.engine.revoke import revoke

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "adapters" / "opencode" / "tests" / "driver.js"
FIXTURE = REPO / "docs" / "consults" / "opencode-recheck-2026-10-16-shape.json"
DUMMY_CONTENT = "Synthetic public Pedigree capture recheck. Marker: F08_RECHECK_DUMMY_READ_OK.\n"
DUMMY_DISPLAY_TEXT = "Synthetic public Pedigree capture recheck. Marker: F08_RECHECK_DUMMY_READ_OK."

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node runtime is not installed")


@pytest.fixture()
def live_server(fresh_graph):
    """The real app on a real localhost socket, with tenant provisioning."""
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="dummy-admin")
    registry = TenantRegistry(db, settings)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db, settings), log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    provisioned: list[str] = []

    class Server:
        def __init__(self) -> None:
            self.db = db
            self.graph = graph
            self.tenant = tenant
            self.base = f"http://127.0.0.1:{port}"

        def make_tenant(self, tenant_id: str) -> dict:
            """Provision through the documented admin endpoint."""
            with httpx.Client(base_url=self.base, timeout=10) as client:
                response = client.post(
                    "/admin/tenants",
                    headers={"X-Admin-Token": "dummy-admin"},
                    json={"id": tenant_id},
                )
            assert response.status_code == 200, response.text
            provisioned.append(tenant_id)
            return response.json()

    try:
        yield Server()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        for tenant_id in provisioned:
            db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant_id})


def expected_project_key(project: Path) -> str:
    real = os.path.realpath(str(project))
    return "p_" + hashlib.sha256(f"pedigree.opencode.project.v1|{real}".encode()).hexdigest()[:16]


def expected_digest(*, rel: str, line_start: int, line_end: int, total_lines: int,
                    truncated: bool, text: str) -> str:
    # Canonical encoding of the observed descriptor (same key order as the adapter).
    descriptor = {"v": 1, "path": rel, "line_start": line_start, "line_end": line_end,
                  "total_lines": total_lines, "truncated": truncated, "text": text}
    canonical = json.dumps(descriptor, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def genuine_job(project: Path, *, session_id: str, call_id: str, phases=("before", "after")) -> dict:
    """The genuine fixture with placeholders substituted, restricted to `phases`."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def substitute(value):
        if isinstance(value, str):
            value = value.replace("$PROJECT\\dummy.txt", str(project / "dummy.txt"))
            value = value.replace("$PROJECT/dummy.txt", str(project / "dummy.txt"))
            return value.replace("$SESSION_ID", session_id).replace("$CALL_ID", call_id)
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    hooks = []
    for event in fixture["tool_events"]:
        phase = "after" if event["hook"].endswith("after") else "before"
        if phase in phases:
            hooks.append({"phase": phase, "input": substitute(event["input"]), "output": substitute(event["output"])})
    job = {"project": str(project), "hooks": hooks}
    rendered = json.dumps(job)
    for placeholder in ("$PROJECT", "$SESSION_ID", "$CALL_ID"):
        assert placeholder not in rendered, f"unsubstituted {placeholder}"
    return job


def replay(job: dict, *, token: str, base: str, tmp_path: Path, name: str) -> list[dict]:
    """Run the driver against the live server; return per-hook results."""
    job_path = tmp_path / f"job-{name}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    env = {
        **os.environ,
        "PEDIGREE_OPENCODE_ENABLED": "1",
        "PEDIGREE_OPENCODE_URL": base,
        "PEDIGREE_OPENCODE_TOKEN": token,
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


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "dummy.txt").write_text(DUMMY_CONTENT, encoding="utf-8")
    return project


def test_genuine_replay_captures_read_view_then_refuses_after_revoke(live_server, tmp_path):
    server = live_server
    project = make_project(tmp_path)
    token = server.make_tenant(server.tenant)["token"]
    sid = "ses_int_genuine"
    project_key = expected_project_key(project)
    server_sid = f"oc_{project_key}_{sid}"
    uri = f"readview:v1/{project_key}/dummy.txt#L1-L1"
    digest = expected_digest(rel="dummy.txt", line_start=1, line_end=1, total_lines=1,
                             truncated=False, text=DUMMY_DISPLAY_TEXT)

    # 1) The genuine fixture is gated (allow) and captured.
    results = replay(genuine_job(project, session_id=sid, call_id="call_int_1"),
                     token=token, base=server.base, tmp_path=tmp_path, name="first")
    assert results == [
        {"ok": True, "value": {"decision": "allow"}},
        {"ok": True, "value": {"captured": True}},
    ], results

    rows = server.db.ro_query(
        server.graph,
        "MATCH (s:Source {uri:$uri}) RETURN s.id, s.content_hash, s.kind, s.integrity, s.tenant",
        {"uri": uri},
    ).result_set
    assert len(rows) == 1, rows
    source_id, content_hash, kind, integrity, tenant_prop = rows[0]
    assert content_hash == digest, "independently recomputed canonical digest must match"
    assert kind == "file"
    assert integrity == "untrusted", "the agent capture channel never asserts trust"
    assert tenant_prop == server.tenant

    session_rows = server.db.ro_query(
        server.graph,
        "MATCH (s:Session {id:$sid}) RETURN s.runtime, s.tenant",
        {"sid": server_sid},
    ).result_set
    assert session_rows == [["opencode", server.tenant]]
    assert read_window(server.db, server.graph, server_sid) == [source_id]

    # 2) A healthy re-read is allowed and converges on the same artifact identity.
    results = replay(genuine_job(project, session_id=sid, call_id="call_int_2"),
                     token=token, base=server.base, tmp_path=tmp_path, name="second")
    assert [result["ok"] for result in results] == [True, True]
    assert read_window(server.db, server.graph, server_sid) == [source_id]
    count = server.db.ro_query(server.graph, "MATCH (s:Source {uri:$uri}) RETURN count(s)",
                               {"uri": uri}).result_set
    assert count == [[1]], "repeat captures converge on one Source (uri + content_hash)"

    # 3) Revoking the captured source denies the next read in that session.
    revoke(server.db, server.graph, server.tenant, root_id=source_id)
    results = replay(genuine_job(project, session_id=sid, call_id="call_int_3", phases=("before",)),
                     token=token, base=server.base, tmp_path=tmp_path, name="revoked")
    assert len(results) == 1, "a denied read never executes: only the before hook ran"
    assert results[0]["ok"] is False
    assert results[0]["code"] == "gate_reverify"
    assert results[0]["message"] == "pedigree: read denied by gate (reverify)"
    count = server.db.ro_query(server.graph, "MATCH (s:Source {uri:$uri}) RETURN count(s)",
                               {"uri": uri}).result_set
    assert count == [[1]], "the denied read captured nothing"


def test_identical_captures_are_isolated_per_tenant(live_server, tmp_path):
    server = live_server
    project = make_project(tmp_path)
    cred_a = server.make_tenant(server.tenant)
    tenant_b = "t" + uuid.uuid4().hex[:10]
    cred_b = server.make_tenant(tenant_b)
    graph_b = graph_name(tenant_b)
    sid = "ses_int_shared"
    project_key = expected_project_key(project)
    server_sid = f"oc_{project_key}_{sid}"
    uri = f"readview:v1/{project_key}/dummy.txt#L1-L1"

    # The same project and runtime session captured under two tenants.
    for name, cred in (("a", cred_a), ("b", cred_b)):
        results = replay(genuine_job(project, session_id=sid, call_id=f"call_tenant_{name}"),
                         token=cred["token"], base=server.base, tmp_path=tmp_path, name=f"tenant-{name}")
        assert [result["ok"] for result in results] == [True, True], results

    source_a = server.db.ro_query(server.graph, "MATCH (s:Source {uri:$uri}) RETURN s.id",
                                  {"uri": uri}).result_set[0][0]
    source_b = server.db.ro_query(graph_b, "MATCH (s:Source {uri:$uri}) RETURN s.id",
                                  {"uri": uri}).result_set[0][0]
    assert source_a != source_b

    # Each graph knows only its own capture, and each session belongs to its tenant.
    assert server.db.ro_query(server.graph, "MATCH (n:Source {id:$id}) RETURN count(n)",
                              {"id": source_b}).result_set == [[0]]
    assert server.db.ro_query(graph_b, "MATCH (n:Source {id:$id}) RETURN count(n)",
                              {"id": source_a}).result_set == [[0]]
    assert server.db.ro_query(server.graph, "MATCH (s:Session {id:$sid}) RETURN s.tenant",
                              {"sid": server_sid}).result_set == [[server.tenant]]
    assert server.db.ro_query(graph_b, "MATCH (s:Session {id:$sid}) RETURN s.tenant",
                              {"sid": server_sid}).result_set == [[tenant_b]]

    # Revoking A's source must not affect tenant B: B still gates allow and captures.
    revoke(server.db, server.graph, server.tenant, root_id=source_a)
    results_a = replay(genuine_job(project, session_id=sid, call_id="call_tenant_a2", phases=("before",)),
                       token=cred_a["token"], base=server.base, tmp_path=tmp_path, name="tenant-a2")
    assert results_a[0]["code"] == "gate_reverify"
    results_b = replay(genuine_job(project, session_id=sid, call_id="call_tenant_b2"),
                       token=cred_b["token"], base=server.base, tmp_path=tmp_path, name="tenant-b2")
    assert [result["ok"] for result in results_b] == [True, True], results_b


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="NTFS case-insensitive volume semantics")
def test_case_variant_paths_converge_on_one_source(live_server, tmp_path):
    """`CASE.TXT` and `case.txt` name one file on Windows; they must mint one Source."""
    server = live_server
    project = make_project(tmp_path)
    (project / "case.txt").write_text("case variant\n", encoding="utf-8")
    token = server.make_tenant(server.tenant)["token"]
    sid = "ses_int_case"
    project_key = expected_project_key(project)
    uri = f"readview:v1/{project_key}/case.txt#L1-L1"
    display_text = "case variant"

    def case_job(call_id: str, file_name: str) -> dict:
        absolute = str(project / file_name)
        display = {
            "type": "file", "path": absolute, "text": display_text,
            "lineStart": 1, "lineEnd": 1, "totalLines": 1, "truncated": False,
        }
        return {
            "project": str(project),
            "hooks": [
                {"phase": "before",
                 "input": {"tool": "read", "sessionID": sid, "callID": call_id},
                 "output": {"args": {"filePath": absolute}}},
                {"phase": "after",
                 "input": {"tool": "read", "sessionID": sid, "callID": call_id, "args": {"filePath": absolute}},
                 "output": {"title": absolute, "output": display_text, "metadata": {"display": display}}},
            ],
        }

    for name, file_name in (("upper", "CASE.TXT"), ("lower", "case.txt")):
        results = replay(case_job(f"call_case_{name}", file_name),
                         token=token, base=server.base, tmp_path=tmp_path, name=f"case-{name}")
        assert [result["ok"] for result in results] == [True, True], results

    digest = expected_digest(rel="case.txt", line_start=1, line_end=1, total_lines=1,
                             truncated=False, text=display_text)
    rows = server.db.ro_query(
        server.graph,
        "MATCH (s:Source {uri:$uri}) RETURN s.id, s.content_hash, s.integrity",
        {"uri": uri},
    ).result_set
    assert len(rows) == 1, rows
    source_id, content_hash, integrity = rows[0]
    assert content_hash == digest
    assert integrity == "untrusted"
    duplicate = server.db.ro_query(
        server.graph,
        "MATCH (s:Source {uri:$uri}) RETURN count(s)",
        {"uri": f"readview:v1/{project_key}/CASE.TXT#L1-L1"},
    ).result_set
    assert duplicate == [[0]], "no case-variant duplicate Source may exist"
    assert read_window(server.db, server.graph, f"oc_{project_key}_{sid}") == [source_id]
