"""Deterministic gate, with materialised containment semantics from ADR-007."""
from __future__ import annotations

import re
import shlex
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import EFFECTS, LIMITS, RISKS, get_settings, graph_name, validate_id, validate_tenant
from ..db import queries as Q
from ..db.client import chunks
from ..errors import InvalidArgument
from ..observability import count_gate
from .blame import _norm_depth, bfs_paths
from .ingest import _validate_conf, _validate_ids, read_window, record_action
from .quota import quota_write

SEVERITY = {"allow": 0, "warn": 1, "reverify": 2, "block": 3}
HOOK_MAP = {"allow": "allow", "warn": "allow", "reverify": "ask", "block": "deny"}
TRUSTED_SUPPORT = frozenset({"human", "scanner"})
BAD = frozenset({"revoked", "tainted", "quarantined"})


@dataclass
class Policy:
    rules: list[dict] = field(default_factory=list)


def load_policy(path=None) -> Policy:
    """Invalid/missing server configuration retains the built-in classifier."""
    try:
        raw = yaml.safe_load(Path(path or get_settings().pedigree_policy_file).read_text(encoding="utf-8"))
        rules = raw.get("rules", []) if isinstance(raw, dict) else []
        valid = []
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, dict) or rule.get("effect") not in EFFECTS or rule.get("risk") not in RISKS:
                continue
            re.compile(rule.get("tool", ".*"), re.I)
            re.compile(rule.get("match", ".*"), re.I)
            valid.append(rule)
        return Policy(valid)
    except (OSError, ValueError, TypeError, re.error, yaml.YAMLError):
        return Policy()


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_shell_segments(command: str):
    """Split on shell separators outside quotes, matching the Claude hook."""
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
# ssh/scp/sudo are matched as command tokens, not as path segments. `\bssh\b`
# treats `cat ~/.ssh/config` as an ssh invocation because `.` is a boundary.
_NETWORK_COMMANDS = frozenset({"ssh", "scp", "sudo"})
_IRREVERSIBLE_TEXT = re.compile(
    r"(?:git\s+push|(?:npm|cargo|docker)\s+(?:publish|push)|kubectl\s+apply|terraform\s+apply|"
    r"\brm\s+[^\n]*-[^\n]*[rf]|curl\s+[^\n]*-X\s*(?:POST|PUT|DELETE|PATCH))",
    re.I,
)
_UNPARSED_COMMAND = re.compile(r"(?<![\w./])(?:ssh|scp|sudo)\b", re.I)


def _command_basename(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _command_segments(summary: str):
    """Return parsed command token lists and segments shlex could not tokenise."""
    parsed, unparsed = [], []
    for segment in split_shell_segments(summary):
        if not segment.strip():
            continue
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            unparsed.append(segment)
            continue
        index = 0
        while index < len(tokens) and _ENV_ASSIGN.match(tokens[index]):
            index += 1
        if index < len(tokens):
            parsed.append(tokens[index:])
    return parsed, unparsed


def _segment_level(tokens: list[str]) -> str | None:
    """high / medium for a real command token. Arguments that merely mention ssh or curl do not count."""
    name = _command_basename(tokens[0])
    rest = " ".join(tokens[1:])
    if name in _NETWORK_COMMANDS:
        return "high"
    if name in {"npm", "cargo"} and re.search(r"\bpublish\b", rest, re.I):
        return "high"
    if name == "docker" and re.search(r"\b(?:push|publish)\b", rest, re.I):
        return "high"
    if name == "kubectl" and re.search(r"\bapply\b", rest, re.I):
        return "high"
    if name == "terraform" and re.search(r"\bapply\b", rest, re.I):
        return "high"
    if name == "git" and re.search(r"\bpush\b", rest, re.I):
        return "high"
    if name == "rm" and re.search(r"(?:^|\s)-[^\s]*[rf]", rest, re.I):
        return "high"
    if name == "curl" and re.search(
            r"(?:(?:-X|--request)\s*(?:POST|PUT|DELETE|PATCH)|-X(?:POST|PUT|DELETE|PATCH)\b)", rest, re.I):
        return "high"
    if name == "git" and re.search(r"\bcommit\b", rest, re.I):
        return "medium"
    return None


def builtin_effect_risk(summary: str):
    parsed, unparsed = _command_segments(summary)
    rank = {"medium": 1, "high": 2}
    best = None
    for tokens in parsed:
        level = _segment_level(tokens)
        if level is not None and (best is None or rank[level] > rank[best]):
            best = level
    if best != "high" and unparsed:
        blob = "\n".join(unparsed)
        if _IRREVERSIBLE_TEXT.search(blob) or _UNPARSED_COMMAND.search(blob):
            best = "high"
        elif best is None and re.search(r"\bgit\s+commit\b", blob, re.I):
            best = "medium"
    if best == "high":
        return ("irreversible", "high")
    if best == "medium":
        return ("reversible", "medium")
    return ("reversible", "low")


def classify_action(policy, tool, summary, *, effect=None, risk=None):
    classified = builtin_effect_risk(summary or "")
    for rule in policy.rules:
        if re.search(rule.get("tool", ".*"), tool, re.I) and re.search(rule.get("match", ".*"), summary, re.I):
            classified = (rule["effect"], rule["risk"])
            break
    return (effect if effect in EFFECTS else classified[0], risk if risk in RISKS else classified[1])


def default_audience(policy, tool, summary=""):
    for rule in policy.rules:
        if re.search(rule.get("tool", ".*"), tool, re.I) and re.search(rule.get("match", ".*"), summary, re.I):
            if "audience" in rule:
                return _validate_conf(rule["audience"])
            break
    return ["public"] if re.search(r"bash|shell|webfetch|websearch|push|publish|network", tool, re.I) else ["local"]


def risk_blocks(risk):
    return risk in {"medium", "high"}


def hook_output(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": HOOK_MAP[decision],
                                   "permissionDecisionReason": reason}}


@quota_write("gate")
def check_action(db, gname, action, *, relied_on=None, session_id=None, policy_path=None,
                 max_depth=12, record=False, tenant=None, trace=None):
    if tenant is not None:
        validate_tenant(tenant)
        if graph_name(tenant) != gname:
            raise InvalidArgument("tenant graph mismatch")
    if record and tenant is None:
        raise InvalidArgument("tenant required to record an action")
    tool, summary = action.get("tool"), action.get("summary", "")
    if not isinstance(tool, str) or not tool or len(tool) > 128:
        raise InvalidArgument("invalid tool name")
    if not isinstance(summary, str) or len(summary) > LIMITS["summary_len"]:
        raise InvalidArgument("invalid summary")
    ids = _validate_ids(list(relied_on if relied_on is not None else action.get("relied_on", [])),
                        LIMITS["relied_on"], "relied_on")
    from_window = not ids
    if session_id:
        validate_id(session_id)
        if not ids:
            ids = read_window(db, gname, session_id, get_settings().pedigree_read_window, trace)
    ids = list(dict.fromkeys(ids))
    depth = _norm_depth(max_depth)
    for key, choices in (("risk", RISKS), ("effect", EFFECTS)):
        if action.get(key) is not None and action[key] not in choices:
            raise InvalidArgument(f"invalid {key}")
    policy = load_policy(policy_path)
    effect, risk = classify_action(policy, tool, summary, effect=action.get("effect"), risk=action.get("risk"))
    audience = _validate_conf(action.get("audience") if action.get("audience") is not None
                              else default_audience(policy, tool, summary))
    decision, reasons, would_verify = "allow", [], []

    def reason(verdict, code, nid=None, path=None, detail=""):
        nonlocal decision
        if SEVERITY[verdict] > SEVERITY[decision]:
            decision = verdict
        reasons.append({"code": code, "node_id": nid, "path": path or [], "detail": detail})
        if verdict == "reverify" and nid and nid not in would_verify:
            would_verify.append(nid)

    def nodes(nids):
        result = {}
        for batch in chunks(list(nids)):
            rows = db.ro_query(gname, Q.Q_GATE_NODES, {"ids": batch}, op="gate.nodes", trace=trace).result_set or []
            for row in rows:
                result[row[0]] = {"status": row[1], "low_integrity": bool(row[2]),
                                  "conf": row[3] or [], "taint_parent": row[4]}
        return result

    def supports(nids):
        result = defaultdict(list)
        for batch in chunks(list(nids)):
            rows = db.ro_query(gname, Q.Q_GATE_SUPPORT, {"ids": batch}, op="gate.support", trace=trace).result_set or []
            for nid, sid, status, by in rows:
                if status == "ok" and by in TRUSTED_SUPPORT:
                    result[nid].append(sid)
        return result

    details = nodes(ids)

    def taint_path(nid, prefix=None):
        path = list(prefix or [nid])
        current = nid
        for _ in range(depth - (len(path) - 1)):
            info = details.get(current)
            if info is None:
                details.update(nodes([current]))
                info = details.get(current)
            if not info or info["status"] == "revoked":
                break
            parent = info["taint_parent"]
            if not parent or parent in path:
                break
            path.append(parent)
            current = parent
        info = details.get(path[-1])
        if info is None:
            details.update(nodes([path[-1]]))
            info = details.get(path[-1])
        note = "" if info and info["status"] == "revoked" else "; taint_parent missing, cyclic, or depth limit reached"
        return path, note

    support = supports([nid for nid in ids if details.get(nid, {}).get("status") == "preserved"])
    for nid in ids:
        info = details.get(nid)
        if info is None:
            reason("reverify", "not_in_graph", nid, [nid], "Dependency is not in the graph")
            continue
        status = info["status"]
        if status in BAD or (status == "preserved" and not support[nid]):
            path, note = taint_path(nid)
            verdict = "block" if risk_blocks(risk) else "warn"
            if from_window and verdict == "warn":
                verdict = "reverify"
            reason(verdict, "tainted_ancestor", nid, path, f"{status}: no trusted containment basis" + note)
        elif status == "preserved":
            reason("allow", "preserved_lineage", nid, [nid, sorted(support[nid])[0]], "Healthy human/scanner-attested support")
        if set(info["conf"]) - set(audience):
            reason("block", "confidentiality_violation", nid, [nid], "Audience lacks required confidentiality tags")
        if info["low_integrity"] and (effect == "irreversible" or risk == "high"):
            reason("reverify", "untrusted_influence", nid, [nid], "Untrusted influence on a high-risk or irreversible action")
        if effect == "irreversible" or risk == "high":
            ancestors = db.ro_query(gname, Q.Q_ANCESTORS, {"id": nid, "depth": depth},
                                    op="gate.ancestors", trace=trace).result_set or []
            preserved = [r[0] for r in ancestors if r[1] == "preserved"]
            frontier = db.ro_query(gname, Q.Q_ANCESTORS, {"id": nid, "depth": depth + 1},
                                   op="gate.frontier", trace=trace).result_set or []
            if len(frontier) > len(ancestors):
                reason("reverify", "lineage_truncated", nid, [nid],
                       "Ancestry exceeds the depth limit; trusted containment cannot be established")
            trusted = supports(preserved)
            untrusted = [p for p in preserved if not trusted[p]]
            if untrusted:
                closure = [nid] + [r[0] for r in ancestors]
                edges = []
                for batch in chunks(closure):
                    edges.extend(db.ro_query(gname, Q.Q_ANCESTOR_EDGES, {"ids": batch},
                                              op="gate.edges", trace=trace).result_set or [])
                parents = defaultdict(list)
                for child, parent, *_ in edges:
                    parents[child].append(parent)
                paths = bfs_paths(parents, nid, set(untrusted), depth)
                for parent in sorted(untrusted):
                    path, note = taint_path(parent, paths[parent])
                    reason("reverify", "preserved_untrusted_support", nid, path, "Ancestor support is agent-asserted only" + note)
    if not ids:
        reason("allow", "warning:no_lineage", detail="No explicit dependencies or session read window")
    result = {"decision": decision, "reasons": reasons, "checked": len(ids),
              "hook": hook_output(decision, "; ".join(r["detail"] for r in reasons)),
              "would_verify": would_verify, "effect": effect, "risk": risk}
    count_gate(decision)
    if record:
        missing = [nid for nid in ids if nid not in details]
        if missing:
            result["recording_error"] = {"code": "not_in_graph", "missing": missing}
            return result
        if session_id:
            session = db.ro_query(gname, Q.Q_GET_SESSION, {"id": session_id},
                                  op="gate.session", trace=trace).result_set or []
            if not session:
                result["recording_error"] = {"code": "not_in_graph", "session_id": session_id}
                return result
        recorded = record_action(db, gname, tenant, tool=tool, summary=summary, relied_on=ids,
                                 effect=effect, risk=risk, decision=decision, session_id=session_id, trace=trace)
        result["action_id"] = recorded.id
    return result
