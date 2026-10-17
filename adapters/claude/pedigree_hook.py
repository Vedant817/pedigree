"""Claude Code command hook. Standalone Python 3.11+, standard library only.

Inputs follow documented Claude hook fields; no captured runtime payloads are bundled.
Network and malformed-input failures are fail-open, with a content-free warning.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WARNING = "Pedigree hook unavailable; continuing without capture or gating."
TIMEOUT = 1.0
MAX_BYTES = 8 * 1024 * 1024
ROLE_ERROR = "Pedigree hook requires an agent token; operator configuration denied."


def validate_agent_config():
    if os.environ.get("PEDIGREE_TOKEN", "").strip().startswith("ped_o_"):
        raise ValueError(ROLE_ERROR)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the tenant credential to an HTTP redirect destination.
        return None


def request(path, payload=None):
    validate_agent_config()
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
    # Never include Write.content, Edit replacement text, prompt, tool output, or URL userinfo.
    if tool == "Bash":
        return str(args.get("command", ""))[:300]
    name = str(tool).lower()
    if name == "websearch":
        return "WebSearch"
    if name == "webfetch":
        captured = web_source(tool, args)
        return captured[0][:300] if captured else "WebFetch"
    return str(args.get("file_path") or args.get("url") or args.get("uri") or tool)[:300]


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_shell_segments(command):
    """Split on shell separators outside quotes. `&` inside a quoted URL stays put."""
    parts, buf, quote = [], [], None
    i, text = 0, command or ""
    while i < len(text):
        ch = text[i]
        if quote == "'":
            buf.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if ch == "\\" and i + 1 < len(text):
                buf.append(ch)
                buf.append(text[i + 1])
                i += 2
                continue
            buf.append(ch)
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in {";", "|", "&", "\n"}:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts
_READ_COMMANDS = frozenset({"cat", "head", "curl", "wget"})
_FLAG_WITH_VALUE = frozenset({
    "-n", "--lines", "-c", "--bytes", "-o", "--output", "-H", "--header", "-A", "--user-agent",
    "-e", "--referer", "-u", "--user", "-m", "--max-time", "--connect-timeout", "-w", "--write-out",
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form",
    "-X", "--request", "--method", "--post-data", "--post-file",
})
_URI_LIMIT = 512


def _basename(token):
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


def command_segments(command):
    """Tokenise a bash command. Unparseable segments are omitted, not guessed."""
    segments = []
    for part in split_shell_segments(command):
        if not part.strip():
            continue
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            continue
        index = 0
        while index < len(tokens) and _ENV_ASSIGN.match(tokens[index]):
            index += 1
        if index < len(tokens):
            segments.append(tokens[index:])
    return segments


def _segment_writes(name, args):
    if name not in {"curl", "wget"}:
        return False
    index = 0
    while index < len(args):
        arg = args[index]
        base = arg.split("=", 1)[0]
        if base in {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form",
                    "--post-data", "--post-file"}:
            return True
        if base in {"-X", "--request", "--method"} or (arg.upper().startswith("-X") and len(arg) > 2):
            if "=" in arg:
                value = arg.split("=", 1)[1]
            elif arg.upper().startswith("-X") and len(arg) > 2 and not arg.startswith("--"):
                value = arg[2:]
            elif index + 1 < len(args):
                value = args[index + 1]
            else:
                value = ""
            if value.upper() not in {"", "GET", "HEAD"}:
                return True
        index += 1
    return False


def _read_operands(args):
    found = []
    index = 0
    while index < len(args):
        arg = args[index]
        base = arg.split("=", 1)[0]
        if arg == "-" or arg.startswith("-"):
            index += 2 if base in _FLAG_WITH_VALUE and "=" not in arg else 1
            continue
        if arg.startswith(("http://", "https://")):
            found.append(("url", arg))
        else:
            found.append(("path", arg))
        index += 1
    return found


def bash_read_targets(command):
    """Paths and http(s) URLs read by cat, head, curl, or wget. Writes are skipped."""
    targets = []
    for tokens in command_segments(command):
        name = _basename(tokens[0])
        args = tokens[1:]
        if name == "sudo" and args:
            while args and args[0].startswith("-"):
                args = args[1:]
            if not args:
                continue
            name = _basename(args[0])
            args = args[1:]
        if name not in _READ_COMMANDS or _segment_writes(name, args):
            continue
        targets.extend(_read_operands(args))
    return targets


def _public_url(url):
    if not isinstance(url, str) or len(url) > _URI_LIMIT or not url.startswith(("http://", "https://")):
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        return None
    return url


def web_source(tool, args):
    """WebFetch URL, or a hash-only WebSearch uri. Query text is not returned."""
    name = str(tool).lower()
    if name == "webfetch":
        url = _public_url(args.get("url") or args.get("uri"))
        if url is None:
            return None
        return url, hashlib.sha256(url.encode()).hexdigest()
    if name == "websearch":
        query = args.get("query") if isinstance(args.get("query"), str) else args.get("q")
        if not isinstance(query, str) or not query.strip():
            return None
        digest = hashlib.sha256(query.encode()).hexdigest()
        return "websearch:sha256:" + digest, digest
    return None


def segment_command(tokens):
    name = _basename(tokens[0])
    args = tokens[1:]
    if name == "sudo":
        while args and args[0].startswith("-"):
            args = args[1:]
        if not args:
            return None
        return _basename(args[0])
    return name


def file_read_events(path, digest, key, send):
    found = send("/v1/artifacts/lookup?" + urllib.parse.urlencode({"key": key}))
    nid = found["node_id"] if found.get("found") else "src_" + secrets.token_hex(8)
    events = []
    if not found.get("found"):
        kind = "rules_file" if Path(path).name in {"CLAUDE.md", "AGENTS.md", "MEMORY.md"} else "file"
        events.append({"type": "source_read", "source_kind": kind, "uri": path,
                       "content_hash": digest, "id": nid})
    events.append({"type": "session_read", "node_id": nid})
    return events


def handle(mode, payload, send=request):
    validate_agent_config()
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
                events.extend(file_read_events(path, digest, key, send))
            else:
                events.append({"type": "action_executed", "tool": tool, "summary": path[:300],
                               "artifacts": [path], "artifact_key": key})
        elif str(tool).lower() in {"webfetch", "websearch"}:
            captured = web_source(tool, args)
            if captured is None:
                return None
            uri, digest = captured
            nid = "src_" + secrets.token_hex(8)
            events.extend([
                {"type": "source_read", "source_kind": "web", "integrity": "untrusted",
                 "uri": uri, "content_hash": digest, "id": nid},
                {"type": "session_read", "node_id": nid},
            ])
        elif tool == "Bash":
            command = str(args.get("command", ""))
            targets = bash_read_targets(command)
            read_ids = []
            for kind, value in targets:
                if kind == "url":
                    uri = _public_url(value)
                    if uri is None:
                        continue
                    nid = "src_" + secrets.token_hex(8)
                    digest = hashlib.sha256(uri.encode()).hexdigest()
                    events.extend([
                        {"type": "source_read", "source_kind": "web", "integrity": "untrusted",
                         "uri": uri, "content_hash": digest, "id": nid},
                        {"type": "session_read", "node_id": nid},
                    ])
                    read_ids.append(nid)
                    continue
                artifact = file_key(value, payload.get("cwd") or os.getcwd())
                if artifact is None or len(artifact[0]) > _URI_LIMIT:
                    continue
                path, digest, key = artifact
                linked = file_read_events(path, digest, key, send)
                events.extend(linked)
                read_ids.append(linked[-1]["node_id"])
            segments = command_segments(command)
            reads_only = bool(segments) and all(segment_command(tokens) in _READ_COMMANDS for tokens in segments)
            if targets and not read_ids and reads_only:
                return None
            action = {"type": "action_executed", "tool": tool, "summary": summary(tool, args)}
            if read_ids:
                action["relied_on"] = read_ids
            events.append(action)
        else:
            events.append({"type": "action_executed", "tool": tool, "summary": summary(tool, args)})
    else:
        raise ValueError("unknown mode")
    send("/v1/events", {"runtime": "claude-code", "session_id": sid, "events": events})
    return None


def main():
    # Configuration errors must not enter the network/malformed-input fail-open path.
    try:
        validate_agent_config()
    except ValueError:
        print(ROLE_ERROR, file=sys.stderr)
        if len(sys.argv) > 1 and sys.argv[1] == "pre":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                "permissionDecision": "deny", "permissionDecisionReason": ROLE_ERROR}}))
        return 2
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
