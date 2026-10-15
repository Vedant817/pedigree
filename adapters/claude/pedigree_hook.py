"""Claude Code command hook. Standalone Python 3.11+, standard library only.

Inputs follow documented Claude hook fields; no captured runtime payloads are bundled.
Network and malformed-input failures are fail-open, with a content-free warning.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WARNING = "Pedigree hook unavailable; continuing without capture or gating."
TIMEOUT = 1.0
MAX_BYTES = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the tenant credential to an HTTP redirect destination.
        return None


def request(path, payload=None):
    base = os.environ.get("PEDIGREE_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    token = os.environ.get("PEDIGREE_TOKEN", "")
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not token:
        raise ValueError("invalid configuration")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=TIMEOUT) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("response too large")
    return json.loads(raw)


def file_key(value, cwd):
    path = Path(value)
    if not path.is_absolute():
        path = Path(cwd) / path
    path = path.resolve()
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return None
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        return None
    digest = hashlib.sha256(content).hexdigest()
    return path.as_posix(), digest, f"{path.as_posix()}@{digest}"


def summary(tool, args):
    # Never include Write.content, Edit replacement text, prompt, or tool output.
    if tool == "Bash":
        return str(args.get("command", ""))[:300]
    return str(args.get("file_path") or args.get("url") or tool)[:300]


def handle(mode, payload, send=request):
    sid = payload["session_id"]
    tool = payload.get("tool_name", "unknown")
    args = payload.get("tool_input") or {}
    if mode == "pre":
        action = {"tool": tool, "summary": summary(tool, args)}
        if tool == "Bash" and len(str(args.get("command", ""))) > 300:
            # The API summary limit must not hide a risky suffix from its classifier.
            action.update({"risk": "high", "effect": "unknown"})
        result = send("/v1/gate", {"session_id": sid, "action": action})
        hook = result["hook"]
        specific = hook["hookSpecificOutput"]
        if specific["permissionDecision"] not in {"deny", "ask", "allow"}:
            raise ValueError("invalid gate hook")
        return hook

    events = [{"type": "session"}]
    if mode == "prompt":
        digest = hashlib.sha256(payload.get("prompt", "").encode()).hexdigest()
        nid = "src_" + secrets.token_hex(8)
        events.extend([{"type": "source_read", "source_kind": "user_prompt", "id": nid,
                        "uri": "prompt:sha256:" + digest, "content_hash": digest},
                       {"type": "session_read", "node_id": nid}])
    elif mode == "post":
        response = payload.get("tool_response")
        if (payload.get("hook_event_name") == "PostToolUseFailure" or payload.get("is_error")
                or isinstance(response, dict) and (response.get("is_error") or response.get("success") is False)):
            return None
        if tool in {"Read", "Write", "Edit", "MultiEdit"}:
            path = args.get("file_path")
            artifact = file_key(path, payload.get("cwd") or os.getcwd()) if path else None
            if artifact is None:
                return None
            path, digest, key = artifact
            if tool == "Read":
                found = send("/v1/artifacts/lookup?" + urllib.parse.urlencode({"key": key}))
                nid = found["node_id"] if found.get("found") else "src_" + secrets.token_hex(8)
                if not found.get("found"):
                    kind = "rules_file" if Path(path).name in {"CLAUDE.md", "AGENTS.md", "MEMORY.md"} else "file"
                    events.append({"type": "source_read", "source_kind": kind, "uri": path,
                                   "content_hash": digest, "id": nid})
                events.append({"type": "session_read", "node_id": nid})
            else:
                events.append({"type": "action_executed", "tool": tool, "summary": path[:300],
                               "artifacts": [path], "artifact_key": key})
        else:
            events.append({"type": "action_executed", "tool": tool, "summary": summary(tool, args)})
    else:
        raise ValueError("unknown mode")
    send("/v1/events", {"runtime": "claude-code", "session_id": sid, "events": events})
    return None


def main():
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise ValueError("input too large")
        output = handle(sys.argv[1], json.loads(raw))
        if output is not None:
            print(json.dumps(output))
    except Exception:
        # Do not include exception text: HTTP errors may contain tokens or payloads.
        print(WARNING, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
