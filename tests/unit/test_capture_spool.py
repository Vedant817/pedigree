import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@pytest.fixture
def hook():
    path = Path(__file__).resolve().parents[2] / "adapters/claude/pedigree_hook.py"
    spec = importlib.util.spec_from_file_location("spool_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_capture_is_durable_and_credential_scoped(hook, monkeypatch, tmp_path):
    monkeypatch.setenv("PEDIGREE_TOKEN", "test-agent-secret")
    monkeypatch.setenv("PEDIGREE_SPOOL_DIR", str(tmp_path))
    calls = []
    def offline(*args):
        calls.append(args)
        raise OSError("offline")
    spool = hook.Spool()
    hook.capture("prompt", {"session_id": "s1", "prompt": "private prompt"}, spool)
    assert not calls
    assert spool.pending() == 1
    with pytest.raises(OSError):
        spool.drain(offline)
    recovered = hook.Spool()
    delivered = []
    recovered.drain(lambda path, body: delivered.append(body) or {"created": [], "delivery_id": body["delivery_id"]})
    assert recovered.pending() == 0
    assert delivered[0]["delivery_id"]
    assert "private prompt" not in str(delivered)
    assert not any(b"test-agent-secret" in file.read_bytes() for file in tmp_path.rglob("*") if file.is_file())
    monkeypatch.setenv("PEDIGREE_TOKEN", "another-agent-secret")
    assert hook.Spool().path != recovered.path


def configured(hook, monkeypatch, tmp_path):
    monkeypatch.setenv("PEDIGREE_TOKEN", "test-agent-secret")
    monkeypatch.setenv("PEDIGREE_SPOOL_DIR", str(tmp_path))
    return hook.Spool()


def test_file_lookup_needs_no_network_and_preserves_artifact_identity(hook, monkeypatch, tmp_path):
    spool = configured(hook, monkeypatch, tmp_path / "outbox")
    file = tmp_path / "evidence.py"
    file.write_text("private content", encoding="utf-8")
    hook.capture("post", {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": str(file)}}, spool)
    delivered = []
    spool.drain(lambda path, body: delivered.append(body) or {"delivery_id": body["delivery_id"]})
    assert delivered[0]["events"][1]["artifact_key"].startswith(file.resolve().as_posix() + "@")
    assert "private content" not in str(delivered)


def test_lost_ack_retains_exact_envelope(hook, monkeypatch, tmp_path):
    spool = configured(hook, monkeypatch, tmp_path)
    hook.capture("post", {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "TOKEN=super-secret command"}}, spool)
    seen = []
    def disconnected(path, body):
        seen.append(body)
        raise OSError("response lost")
    with pytest.raises(OSError):
        spool.drain(disconnected)
    spool.drain(lambda path, body: seen.append(body) or {"delivery_id": body["delivery_id"]})
    assert seen[0] == seen[1]
    assert "super-secret" not in str(seen)


def test_storage_full_corruption_and_identity_switch_are_visible(hook, monkeypatch, tmp_path):
    spool = configured(hook, monkeypatch, tmp_path)
    monkeypatch.setattr(spool, "MAX_ITEMS", 1)
    hook.capture("prompt", {"session_id": "s1"}, spool)
    with pytest.raises(ValueError, match="full"):
        hook.capture("prompt", {"session_id": "s1"}, spool)
    assert spool.pending() == 1
    monkeypatch.setenv("PEDIGREE_URL", "http://127.0.0.1:9999")
    with pytest.raises(ValueError, match="endpoint changed"):
        spool.drain(lambda *_: pytest.fail("must not send across endpoint identity"))
    spool.path.write_bytes(b"corrupt database")
    with pytest.raises(sqlite3.DatabaseError):
        spool.pending()


def test_interprocess_replay_is_serial_and_enqueue_is_not_network_blocked(hook, monkeypatch, tmp_path):
    active = 0
    max_active = 0
    seen = []
    paths = []
    entered = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal active, max_active
            paths.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            active += 1
            max_active = max(max_active, active)
            entered.set()
            time.sleep(0.1)
            seen.append(body["delivery_id"])
            response = json.dumps({"delivery_id": body["delivery_id"]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            active -= 1
        def log_message(self, *_):
            pass
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        monkeypatch.setenv("PEDIGREE_URL", f"http://127.0.0.1:{server.server_port}")
        spool = configured(hook, monkeypatch, tmp_path)
        for _ in range(4):
            hook.capture("prompt", {"session_id": "s1"}, spool)
        command = [sys.executable, "-I", "-S", hook.__file__, "replay"]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy()) for _ in range(2)]
        try:
            assert entered.wait(3)
            # A separate queue connection can persist while replay waits on HTTP.
            hook.capture("prompt", {"session_id": "s1"}, spool)
            for child in children:
                output, error = child.communicate(timeout=10)
                assert child.returncode == 0, (output, error)
            assert max_active == 1
            assert len(seen) == len(set(seen)) == 5
            assert spool.pending() == 0
            for _ in range(5):
                hook.capture("prompt", {"session_id": "s1"}, spool)
            checked = subprocess.run([sys.executable, "-I", "-S", hook.__file__, "pre"],
                                     input=json.dumps({"session_id": "s1", "tool_name": "Write"}),
                                     text=True, capture_output=True, env=os.environ.copy(), timeout=8)
            assert checked.returncode == 0
            assert json.loads(checked.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
            assert spool.pending() == 2
            assert len(seen) == 8 and paths == ["/v1/events"] * 8
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate()
            server.shutdown()
            worker.join(timeout=2)


@settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.text(max_size=100), min_size=1, max_size=8))
def test_fifo_immutable_replay_property(hook, monkeypatch, tmp_path, prompts):
    import hashlib
    spool = configured(hook, monkeypatch, tmp_path)
    for prompt in prompts:
        hook.capture("prompt", {"session_id": "property_session", "prompt": prompt}, spool)
    seen = []
    spool.drain(lambda path, body: seen.append(body) or {"delivery_id": body["delivery_id"]})
    assert spool.pending() == 0
    assert len({body["delivery_id"] for body in seen}) == len(prompts)
    assert [body["events"][1]["content_hash"] for body in seen] == [hashlib.sha256(prompt.encode()).hexdigest() for prompt in prompts]
