"""Claude Code command hook. Standalone Python 3.11+, standard library only.

Inputs follow documented Claude hook fields; no captured runtime payloads are bundled.
Capture is durably queued before delivery. Gates deny when delivery or checking fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import sqlite3
import sys
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

WARNING = "Pedigree capture pending or unavailable; restore connectivity and run pedigree_hook.py replay."
GATE_ERROR = "Pedigree cannot verify this action. Restore capture delivery and service connectivity, then retry."
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


_USERINFO_URL = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@", re.I)
_AUTH_VALUE = re.compile(
    r"""((?:authorization|proxy-authorization)\s*[:=]\s*)(?:bearer\s+\S+|"[^"]*"|'[^']*'|\S+)""",
    re.I,
)
_HEADER_VALUE = re.compile(
    r"""((?:cookie|x-api-key)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|\S+)""",
    re.I,
)
_CREDENTIAL_FLAG = re.compile(
    r"""((?:--user|--password|-u)(?:=|\s+))(?:"[^"]*"|'[^']*'|\S+)""",
    re.I,
)


def redact_command(command):
    """Drop URL userinfo and credential header or flag values before anything is sent."""
    text = _USERINFO_URL.sub(r"\1", command or "")
    text = _AUTH_VALUE.sub(r"\1[redacted]", text)
    text = _HEADER_VALUE.sub(r"\1[redacted]", text)
    return _CREDENTIAL_FLAG.sub(r"\1[redacted]", text)


def summary(tool, args):
    # Never include Write.content, Edit replacement text, prompt, tool output, or URL userinfo.
    if tool == "Bash":
        return redact_command(str(args.get("command", "")))[:300]
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
# Value-taking flags are per command. cat -n/-A/-e do not consume the path.
_VALUE_FLAGS = {
    "head": frozenset({"-n", "--lines", "-c", "--bytes"}),
    "curl": frozenset({
        "-c", "-o", "--output", "-H", "--header", "-A", "--user-agent",
        "-e", "--referer", "-u", "--user", "-m", "--max-time", "--connect-timeout", "-w", "--write-out",
        "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
        "-F", "--form", "--form-string", "-X", "--request", "--method", "--post-data", "--post-file",
        "--json", "-T", "--upload-file",
    }),
    "wget": frozenset({
        "-O", "--output-document", "-o", "--output-file", "-P", "--directory-prefix",
        "-e", "--execute", "--post-data", "--post-file", "--body-data", "--body-file",
    }),
}
_WRITE_FLAGS = frozenset({
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
    "-F", "--form", "--form-string", "--post-data", "--post-file",
    "--json", "-T", "--upload-file", "--body-data", "--body-file",
})
_SUDO_VALUE = frozenset({
    "-u", "-g", "-h", "-p", "-C", "-r", "-t", "-U",
    "--user", "--group", "--host", "--prompt", "--close-from", "--role", "--type", "--other-user",
})
_ENV_VALUE = frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"})
_SHELLS = frozenset({"bash", "sh", "dash", "zsh", "ksh"})
_URI_LIMIT = 512
_WALK_LIMIT = 3


def _basename(token):
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _prepare_command(command):
    """Expand $'…' and turn bare backslashes into slashes so shlex keeps Windows paths."""
    text = command or ""
    out = []
    i = 0
    quote = None
    while i < len(text):
        ch = text[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if ch == "\\" and i + 1 < len(text):
                out.append(ch)
                out.append(text[i + 1])
                i += 2
                continue
            out.append(ch)
            if ch == '"':
                quote = None
            i += 1
            continue
        if text.startswith("$'", i):
            j = i + 2
            body = []
            while j < len(text) and text[j] != "'":
                if text[j] == "\\" and j + 1 < len(text):
                    body.append(text[j + 1])
                    j += 2
                    continue
                body.append(text[j])
                j += 1
            if j < len(text) and text[j] == "'":
                inner = "".join(body).replace("'", "'\\''")
                out.append("'")
                out.append(inner)
                out.append("'")
                i = j + 1
                continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            continue
        out.append("/" if ch == "\\" else ch)
        i += 1
    return "".join(out)


def _peel(tokens, depth, walk):
    """Yield argv lists after sudo, env, command, exec, eval, and shell -c."""
    if not tokens or depth > _WALK_LIMIT:
        return
    name = _basename(tokens[0])
    args = tokens[1:]
    if name == "sudo":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            base = args[index].split("=", 1)[0]
            index += 2 if base in _SUDO_VALUE and "=" not in args[index] else 1
        yield from _peel(args[index:], depth + 1, walk)
        return
    if name == "env":
        index = 0
        while index < len(args) and (args[index].startswith("-") or _ENV_ASSIGN.match(args[index])):
            base = args[index].split("=", 1)[0]
            index += 2 if base in _ENV_VALUE and "=" not in args[index] else 1
        yield from _peel(args[index:], depth + 1, walk)
        return
    if name == "command":
        index = 0
        while index < len(args) and args[index] in {"-p", "-v", "-V"}:
            index += 1
        yield from _peel(args[index:], depth + 1, walk)
        return
    if name == "exec":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] in {"-a", "-c"} and "=" not in args[index] else 1
        yield from _peel(args[index:], depth + 1, walk)
        return
    if name == "eval" and args:
        walk(" ".join(args), depth + 1)
        return
    if name in _SHELLS:
        script = None
        index = 0
        while index < len(args):
            if args[index] == "-c" and index + 1 < len(args):
                script = args[index + 1]
                break
            if args[index].startswith("-c") and len(args[index]) > 2 and not args[index].startswith("--"):
                script = args[index][2:]
                break
            index += 1
        if script is not None:
            walk(script, depth + 1)
            return
    yield tokens


def command_segments(command):
    """Tokenise a bash command. Unparseable segments are omitted, not guessed."""
    found = []

    def walk(text, depth):
        if depth > _WALK_LIMIT:
            return
        for part in split_shell_segments(_prepare_command(text)):
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
                found.extend(_peel(tokens[index:], depth, walk))

    walk(command, 0)
    return found


def _segment_writes(name, args):
    if name not in {"curl", "wget"}:
        return False
    index = 0
    while index < len(args):
        arg = args[index]
        base = arg.split("=", 1)[0]
        if base in _WRITE_FLAGS:
            return True
        if base in {"-X", "--request", "--method"} or (
                arg.upper().startswith("-X") and len(arg) > 2 and not arg.startswith("--")):
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


def _read_operands(name, args):
    found = []
    flags = _VALUE_FLAGS.get(name, frozenset())
    index = 0
    while index < len(args):
        arg = args[index]
        base = arg.split("=", 1)[0]
        if arg in {">", ">>", ">&"}:
            index += 2
            continue
        if arg.startswith((">", "1>", "2>")):
            index += 1
            continue
        if arg == "-" or arg.startswith("-"):
            index += 2 if base in flags and "=" not in arg else 1
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
        if name not in _READ_COMMANDS or _segment_writes(name, args):
            continue
        targets.extend(_read_operands(name, args))
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
    return _basename(tokens[0]) if tokens else None


def file_read_events(path, digest, key, send, durable=False):
    found = {} if durable else send("/v1/artifacts/lookup?" + urllib.parse.urlencode({"key": key}))
    nid = found["node_id"] if found.get("found") else "src_" + secrets.token_hex(8)
    events = []
    if not found.get("found"):
        kind = "rules_file" if Path(path).name in {"CLAUDE.md", "AGENTS.md", "MEMORY.md"} else "file"
        events.append({"type": "source_read", "source_kind": kind, "uri": path,
                       "content_hash": digest, "id": nid})
        if durable:
            events[-1]["artifact_key"] = key
    events.append({"type": "session_read", "node_id": nid})
    return events


def handle(mode, payload, send=request, durable=False):
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
                events.extend(file_read_events(path, digest, key, send, durable))
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
                linked = file_read_events(path, digest, key, send, durable)
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


class Spool:
    """Private bounded SQLite queue; an immediate transaction serializes send+ack.

    The credential only chooses a namespace. It is never stored. Pending entries
    survive hook exits and process death; a successful acknowledgement alone deletes
    an entry. Old credential namespaces require that original credential to drain.
    """
    MAX_ITEMS = 1000
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self):
        validate_agent_config()
        base = os.environ.get("PEDIGREE_URL", "http://127.0.0.1:8000").rstrip("/")
        token = os.environ.get("PEDIGREE_TOKEN", "")
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not token or parsed.query or parsed.fragment:
            raise ValueError("invalid configuration")
        self.identity = hashlib.sha256((base + "\0" + token).encode()).hexdigest()
        root = Path(os.environ.get("PEDIGREE_SPOOL_DIR", str(Path.home() / ".pedigree" / "spool")))
        if root.is_symlink():
            raise ValueError("unsafe spool directory")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / (self.identity + ".sqlite3")
        if self.path.is_symlink():
            raise ValueError("unsafe spool file")
        # Create with private mode before SQLite sees the file (POSIX umask independent).
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")

    @contextmanager
    def connect(self, replay_lock=False):
        path = self.path.with_suffix(".replay-lock") if replay_lock else self.path
        if path.is_symlink():
            raise ValueError("unsafe spool file")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        connection = sqlite3.connect(path, timeout=2.0)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA max_page_count=4096")
            with connection:
                yield connection
        finally:
            connection.close()

    def pending(self):
        with self.connect() as connection:
            return connection.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def enqueue(self, body):
        raw = json.dumps(body, separators=(",", ":"))
        if len(raw.encode()) > 262144:
            raise ValueError("capture too large")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count, size = connection.execute("SELECT count(*), coalesce(sum(length(CAST(body AS BLOB))),0) FROM outbox").fetchone()
            if count >= self.MAX_ITEMS or size + len(raw.encode()) > self.MAX_BYTES:
                raise ValueError("capture spool full; replay pending captures before retrying")
            connection.execute("INSERT INTO outbox(body) VALUES (?)", (raw,))

    def drain(self, send=request, limit=20):
        base = os.environ.get("PEDIGREE_URL", "http://127.0.0.1:8000").rstrip("/")
        token = os.environ.get("PEDIGREE_TOKEN", "")
        if hashlib.sha256((base + "\0" + token).encode()).hexdigest() != self.identity:
            raise ValueError("capture credential or endpoint changed")
        # Use a separate SQLite lock file so network waits never block enqueue.
        # SQLite releases this OS-level lock automatically on process death.
        with self.connect(replay_lock=True) as replay_lock:
            replay_lock.execute("BEGIN IMMEDIATE")
            for _ in range(limit):
                with self.connect() as connection:
                    row = connection.execute("SELECT seq,body FROM outbox ORDER BY seq LIMIT 1").fetchone()
                if row is None:
                    return
                body = json.loads(row[1])
                result = send("/v1/events", body)
                if not isinstance(result, dict) or result.get("delivery_id") != body["delivery_id"]:
                    raise ValueError("server did not acknowledge durable delivery; upgrade service")
                with self.connect() as connection:
                    connection.execute("DELETE FROM outbox WHERE seq=?", (row[0],))


def capture(mode, payload, spool):
    """Construct a sanitized immutable envelope with zero network operations."""
    def collect(path, body=None):
        if path != "/v1/events":
            raise ValueError("unexpected capture network operation")
        body["delivery_id"] = "delivery_" + secrets.token_hex(16)
        for event in body["events"]:
            if event["type"] == "action_executed":
                event["id"] = "act_" + secrets.token_hex(16)
                if event.get("tool") == "Bash":
                    # Shell arguments can contain arbitrary credentials. Keep only the
                    # tool name and conservative classification in durable storage.
                    event.update(summary="Bash", risk="high", effect="unknown")
        spool.enqueue(body)
    handle(mode, payload, collect, durable=True)


def denied_gate():
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": GATE_ERROR}}


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
        mode = sys.argv[1]
        spool = Spool()
        if mode == "replay":
            spool.drain()
            if spool.pending():
                raise ValueError("capture still pending")
            return 0
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise ValueError("input too large")
        payload = json.loads(raw)
        if mode == "pre":
            # Stay below the shipped ten-second runtime hook deadline. A backlog
            # larger than this short drain produces deny, never a hook timeout.
            spool.drain(limit=3)
            if spool.pending():
                raise ValueError("capture still pending")
            output = handle(mode, payload)
        else:
            capture(mode, payload, spool)
            spool.drain(limit=3)
            output = None
        if output is not None:
            print(json.dumps(output))
    except Exception:
        # Do not include exception text: HTTP errors may contain tokens or payloads.
        print(WARNING, file=sys.stderr)
        if len(sys.argv) > 1 and sys.argv[1] == "pre":
            print(json.dumps(denied_gate()))
            return 0
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
