"""Synthetic hook payloads; these are protocol tests, not captured Claude sessions."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "adapters/claude/pedigree_hook.py"


@pytest.fixture
def hook():
    spec = importlib.util.spec_from_file_location("claude_hook", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("decision", ["deny", "ask", "allow"])
def test_pre_returns_full_server_hook_without_risk_override(hook, decision):
    calls = []
    expected = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                "permissionDecision": decision, "permissionDecisionReason": "server reason"}}

    def request(path, payload=None):
        calls.append((path, payload))
        return {"hook": expected}

    result = hook.handle("pre", {"session_id": "sess_test", "tool_name": "Bash",
                                 "tool_input": {"command": "git push origin main"}}, request)
    assert result == expected
    assert calls == [("/v1/gate", {"session_id": "sess_test", "action": {
        "tool": "Bash", "summary": "git push origin main"}})]


def test_long_bash_command_cannot_hide_risk_after_summary_limit(hook):
    calls = []
    expected = {"hookSpecificOutput": {"permissionDecision": "ask"}}
    command = "echo " + "x" * 300 + "; git push origin main"
    hook.handle("pre", {"session_id": "sess_test", "tool_name": "Bash",
                        "tool_input": {"command": command}},
                lambda path, payload=None: calls.append((path, payload)) or {"hook": expected})
    action = calls[0][1]["action"]
    assert len(action["summary"]) == 300
    assert action["risk"] == "high"
    assert action["effect"] == "unknown"


def test_read_links_existing_artifact_without_minting_source(hook, tmp_path):
    file = tmp_path / "a.py"
    file.write_bytes(b"hello")
    calls = []

    def request(path, payload=None):
        calls.append((path, payload))
        return {"found": True, "node_id": "act_previous"} if "lookup" in path else {"created": []}

    hook.handle("post", {"session_id": "sess_test", "tool_name": "Read",
                         "tool_input": {"file_path": str(file)}}, request)
    assert hashlib.sha256(b"hello").hexdigest() in calls[0][0]
    assert calls[-1][1]["events"] == [{"type": "session"},
        {"type": "session_read", "node_id": "act_previous"}]


def test_write_hashes_current_bytes_and_does_not_send_content(hook, tmp_path):
    file = tmp_path / "a.py"
    file.write_bytes(b"private file body")
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Write",
                         "tool_input": {"file_path": str(file), "content": "private file body"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    event = calls[-1][1]["events"][-1]
    assert event["artifact_key"] == f"{file.resolve().as_posix()}@{hashlib.sha256(file.read_bytes()).hexdigest()}"
    assert event["artifacts"] == [file.resolve().as_posix()]
    assert "private file body" not in json.dumps(calls)


def test_prompt_is_hash_only_and_read_linked(hook):
    calls = []
    hook.handle("prompt", {"session_id": "sess_test", "prompt": "private prompt"},
                lambda path, payload=None: calls.append((path, payload)) or {})
    events = calls[-1][1]["events"]
    assert events[1]["source_kind"] == "user_prompt"
    assert events[-1]["node_id"] == events[1]["id"]
    assert "private prompt" not in json.dumps(calls)


def test_read_missing_file_does_not_claim_capture(hook, tmp_path):
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Read",
                         "tool_input": {"file_path": str(tmp_path / "absent")}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    assert not calls


def test_subprocess_stdlib_only_and_network_failure_denies():
    env = {**os.environ, "PEDIGREE_URL": "http://127.0.0.1:1", "PEDIGREE_TOKEN": "private-token"}
    result = subprocess.run([sys.executable, "-I", "-S", str(HOOK), "pre"],
                            input=json.dumps({"session_id": "sess_test", "tool_name": "Bash",
                                              "tool_input": {"command": "private-command"}}),
                            text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "restore connectivity" in result.stderr


def test_operator_configuration_denied_before_network_or_fail_open(hook, monkeypatch):
    monkeypatch.setenv("PEDIGREE_TOKEN", "ped_o_synthetic_operator_only")
    calls = []
    with pytest.raises(ValueError, match="agent token"):
        hook.handle("pre", {"session_id": "sess_test"},
                    lambda *args: calls.append(args) or {
                        "hook": {"hookSpecificOutput": {"permissionDecision": "allow"}}})
    assert calls == []
    env = {**os.environ, "PEDIGREE_URL": "http://127.0.0.1:1"}
    result = subprocess.run([sys.executable, "-I", "-S", str(HOOK), "pre"],
                            input="malformed", text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 2
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "agent token" in result.stderr
    assert "continuing without" not in result.stderr
    assert env["PEDIGREE_TOKEN"] not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", [{"hook_event_name": "PostToolUseFailure"},
                                     {"tool_response": {"is_error": True}},
                                     {"tool_response": {"success": False}}])
def test_failed_tool_is_not_recorded_as_executed(hook, failure):
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash", **failure},
                lambda path, payload=None: calls.append((path, payload)))
    assert calls == []


@pytest.mark.parametrize("raw", [b"{bad json", b"x" * 262145], ids=["malformed", "oversized"])
def test_malformed_or_oversized_input_denies_gate(raw):
    result = subprocess.run([sys.executable, "-I", "-S", str(HOOK), "pre"],
                            input=raw, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert b"replay" in result.stderr
    assert b"Traceback" not in result.stderr


def test_file_limit_does_not_hash_or_emit_read(hook, tmp_path):
    file = tmp_path / "large"
    with file.open("wb") as stream:
        stream.truncate(hook.MAX_BYTES + 1)
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Read",
                         "tool_input": {"file_path": str(file)}},
                lambda path, payload=None: calls.append((path, payload)))
    assert calls == []


def test_new_file_read_records_hash_and_read_link(hook, tmp_path):
    file = tmp_path / "AGENTS.md"
    file.write_bytes(b"rule")
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Read",
                         "cwd": str(tmp_path), "tool_input": {"file_path": "AGENTS.md"}},
                lambda path, payload=None: calls.append((path, payload)) or {"found": False})
    events = calls[-1][1]["events"]
    assert events[1]["source_kind"] == "rules_file"
    assert events[1]["content_hash"] == hashlib.sha256(b"rule").hexdigest()
    assert events[2]["node_id"] == events[1]["id"]


def test_webfetch_records_untrusted_web_source_and_read(hook):
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "WebFetch",
                         "tool_input": {"url": "https://user:secret@example.com/readme"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    assert calls == []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "WebFetch",
                         "tool_input": {"url": "https://example.com/readme", "prompt": "private page"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    events = calls[-1][1]["events"]
    source = events[1]
    assert source["source_kind"] == "web"
    assert source["integrity"] == "untrusted"
    assert source["uri"] == "https://example.com/readme"
    assert source["content_hash"] == hashlib.sha256(b"https://example.com/readme").hexdigest()
    assert events[2] == {"type": "session_read", "node_id": source["id"]}
    assert "private page" not in json.dumps(calls)
    assert "secret" not in json.dumps(calls)


def test_websearch_is_hash_only(hook):
    calls = []
    hook.handle("pre", {"session_id": "sess_test", "tool_name": "WebSearch",
                        "tool_input": {"query": "private query"}},
                lambda path, payload=None: calls.append((path, payload)) or {
                    "hook": {"hookSpecificOutput": {"permissionDecision": "allow"}}})
    assert "private query" not in json.dumps(calls)
    assert calls[0][1]["action"]["summary"] == "WebSearch"
    hook.handle("post", {"session_id": "sess_test", "tool_name": "WebSearch",
                         "tool_input": {"query": "private query"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    source = calls[-1][1]["events"][1]
    assert source["uri"] == "websearch:sha256:" + hashlib.sha256(b"private query").hexdigest()
    assert source["source_kind"] == "web"
    assert "private query" not in json.dumps(calls)


def test_bash_cat_links_only_the_file_it_read(hook, tmp_path):
    file = tmp_path / "notes.py"
    file.write_bytes(b"private file body")
    calls = []

    def request(path, payload=None):
        calls.append((path, payload))
        return {"found": False}

    command = "cat " + file.resolve().as_posix()
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash", "cwd": str(tmp_path),
                         "tool_input": {"command": command}}, request)
    events = calls[-1][1]["events"]
    source = next(event for event in events if event["type"] == "source_read")
    assert source["source_kind"] == "file"
    assert source["uri"] == file.resolve().as_posix()
    assert events[-1]["relied_on"] == [source["id"]]
    assert events[-1]["tool"] == "Bash"
    assert "private file body" not in json.dumps(calls)


def test_quoted_query_ampersand_stays_one_url(hook):
    calls = []
    command = 'curl -fsSL "https://example.com/a?x=1&y=2"'
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash",
                         "tool_input": {"command": command}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    events = calls[-1][1]["events"]
    assert events[1]["uri"] == "https://example.com/a?x=1&y=2"
    assert [event["type"] for event in events].count("source_read") == 1


def test_cat_flags_and_sudo_user_still_record_the_file(hook, tmp_path):
    file = tmp_path / "notes.py"
    file.write_bytes(b"private file body")
    path = file.resolve().as_posix()

    def posted(command):
        calls = []
        hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash", "cwd": str(tmp_path),
                             "tool_input": {"command": command}},
                    lambda route, payload=None: calls.append((route, payload)) or {"found": False})
        events = calls[-1][1]["events"]
        source = next(event for event in events if event["type"] == "source_read")
        assert source["uri"] == path
        assert events[-1]["relied_on"] == [source["id"]]
        assert any(event["type"] == "session_read" and event["node_id"] == source["id"] for event in events)

    posted("cat -n " + path)
    posted("sudo -u root cat " + path)
    posted("head -n 5 " + path)


def test_write_shaped_curl_and_wget_are_not_reads(hook):
    calls = []

    def post(command):
        calls.clear()
        hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash",
                             "tool_input": {"command": command}},
                    lambda route, payload=None: calls.append((route, payload)) or {})
        events = calls[-1][1]["events"]
        assert [event["type"] for event in events] == ["session", "action_executed"]
        assert "relied_on" not in events[-1]

    post("curl --json '{\"a\":1}' https://example.com/api")
    post("curl --data-ascii=hello https://example.com")
    post("wget --body-data=hello https://example.com")
    post("curl --request POST https://example.com/api")


def test_bash_summary_redacts_secrets(hook):
    calls = []
    command = 'curl -H "Authorization: Bearer sk-live" https://alice:s3cr3t@example.com/private && true'
    hook.handle("pre", {"session_id": "sess_test", "tool_name": "Bash", "tool_input": {"command": command}},
                lambda route, payload=None: calls.append((route, payload)) or {
                    "hook": {"hookSpecificOutput": {"permissionDecision": "allow"}}})
    body = json.dumps(calls)
    assert "sk-live" not in body
    assert "s3cr3t" not in body
    assert "alice" not in body
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash", "tool_input": {"command": command}},
                lambda route, payload=None: calls.append((route, payload)) or {})
    body = json.dumps(calls)
    assert "sk-live" not in body
    assert "s3cr3t" not in body


def test_bash_curl_get_reads_url_and_post_does_not(hook):
    calls = []
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash",
                         "tool_input": {"command": "curl -fsSL https://example.com/install.sh"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    events = calls[-1][1]["events"]
    assert events[1]["uri"] == "https://example.com/install.sh"
    assert events[-1]["relied_on"] == [events[1]["id"]]
    assert any(event["type"] == "session_read" and event["node_id"] == events[1]["id"] for event in events)
    calls.clear()
    hook.handle("post", {"session_id": "sess_test", "tool_name": "Bash",
                         "tool_input": {"command": "curl -X POST https://example.com/api"}},
                lambda path, payload=None: calls.append((path, payload)) or {})
    posted = calls[-1][1]["events"]
    assert [event["type"] for event in posted] == ["session", "action_executed"]
    assert "relied_on" not in posted[-1]


def test_synthetic_fixture_replay(hook):
    fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/claude/synthetic-session.jsonl"
    calls = []

    def request(path, payload=None):
        calls.append((path, payload))
        if path == "/v1/gate":
            return {"hook": {"hookSpecificOutput": {"permissionDecision": "allow"}}}
        return {"found": False}

    for line in fixture.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        item = json.loads(line)
        hook.handle(item["mode"], item["payload"], request)
    gate = calls[0][1]["action"]
    assert gate["summary"] == "cat ~/.ssh/config"
    assert "risk" not in gate
    bodies = json.dumps(calls)
    assert "https://example.com/readme" in bodies
    assert "private query" not in bodies
    assert "websearch:sha256:" in bodies


def test_subprocess_stdlib_http_roundtrip():
    observed = []
    expected = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                "permissionDecision": "deny", "permissionDecisionReason": "synthetic taint"}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append((self.path, self.headers.get("Authorization"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = json.dumps({"decision": "block", "hook": expected}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            env = {**os.environ, "PEDIGREE_URL": f"http://127.0.0.1:{server.server_port}",
                   "PEDIGREE_TOKEN": "synthetic-token"}
            result = subprocess.run([sys.executable, "-I", "-S", str(HOOK), "pre"],
                                    input=json.dumps({"session_id": "sess_test", "tool_name": "Bash",
                                                      "tool_input": {"command": "git push"}}),
                                    text=True, capture_output=True, env=env, timeout=5)
        finally:
            server.shutdown()
            worker.join(timeout=2)
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == expected
    assert observed == [("/v1/gate", "Bearer synthetic-token", {
        "session_id": "sess_test", "action": {"tool": "Bash", "summary": "git push"}})]
