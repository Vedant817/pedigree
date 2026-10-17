"""Brutal heavy-user dogfood harness for Pedigree (the orchestrator runs this after every feature).

Usage
-----
    python scripts/dogfood.py                        # spawn a server on a free port (8100-8999)
    python scripts/dogfood.py --base-url URL         # attach to an already-running server
    python scripts/dogfood.py --strict               # expected-failures count as failures

Default (spawn) mode starts `uvicorn pedigree.api.app:create_app --factory` with a *fresh*
environment (every PEDIGREE_*/FALKOR_* variable dropped) and a random `PEDIGREE_ADMIN_TOKEN`,
waits for `/readyz`, runs the scenario table below, kills the server, cleans up every tenant
graph and registry row it created, writes `scratch/dogfood/<timestamp>.md` (scratch/ is
gitignored) and prints a summary table. Exit code 0 iff every scenario matches its expectation
row; 1 otherwise (listing stale expectations to flip). SKIP rows never affect the exit code.

The expectation table below is the single place to flip rows as fixes land. `expect="pass"` rows
are regression guards; `expect="expected-fail"` rows are known-open issues from FIX_PROMPT.md and
MUST flip to "pass" (and will be reported as STALE until they do) once the cited P-item lands.

Notes on proven-by-probe realities this harness encodes (measured on the live FalkorDB v4.22.1,
tree `561b7e2`; see docs/qa/P-010.md and the report this tool writes):

- P-013 (S01): FIXED - admin auth is fail-closed on any registry state; the `has_tenants()` gate is
  gone. S01 proves it non-destructively: no-token calls 401 AND `api/routes/admin.py` contains no
  `has_tenants` reference (bypass impossible by construction); the empty-registry proof lives in
  `tests/security/test_admin_auth.py` (`test_fresh_registry_bootstrap_is_fail_closed`).
- P-016 (S16/S17): fixed in tree at `6340a5c` + `561b7e2` (MCP stdio `initialize` + tool calls
  work; `GET /mcp` is served from the API process). The rows below therefore expect PASS with the
  P-016 citation and a "flip back if it regresses" note; if the fix regresses they FAIL and exit 1.
- P-022 (S14): no pedigree metric is registered anywhere in `src/`, so `/metrics` today exposes
  only `python_gc_*` / `python_info`. S14 asserts the target state (200 + a "pedigree" series) and
  is EXPECTED-FAIL until P-022 lands.
- S11 forged `Content-Length`: h11 rejects a non-numeric content-length at the protocol level
  before BodySizeMiddleware runs, so the observed 400 comes from uvicorn ("Invalid HTTP request
  received."). Both layers agree on 400, so the row asserts the status only.
- S08 requires the typed 422 `invalid_argument` envelope; S09 checks its error containment.

Environment assumptions: the harness process and the spawned server talk to the same FalkorDB
(default 127.0.0.1:6379) for cleanup; cleanup only ever deletes ids this run created and never
enumerates or deletes other tenants' data (repo data-safety rule).

No new dependencies (stdlib + httpx + mcp), no LLM/network calls beyond localhost, no MULTI/EXEC,
all Cypher used for cleanup is static + parameterised.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp import Client, StdioServerParameters

from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db

ROOT = Path(__file__).resolve().parents[1]
SCRATCH_DIR = ROOT / "scratch" / "dogfood"
PORT_RANGE = (8100, 8999)
TOKEN_RE = re.compile(r"ped_[A-Za-z0-9_\-]{6,}")
UI_MARKER = "Lineage workspace"

#: Registry graph used by TenantRegistry (`graph_name("registry")`); never enumerate its tenants,
#: only count them (S01/S02 need emptiness, cleanup deletes exactly the ids this run created).
REGISTRY_GRAPH = graph_name("registry")

#: Cleanup Cypher (static + parameterised).
Q_REGISTRY_COUNT = "MATCH (t:Tenant) RETURN count(t)"
Q_REGISTRY_EXISTS = "MATCH (t:Tenant {id:$id}) RETURN t.id"
Q_REGISTRY_DELETE = "MATCH (t:Tenant {id:$id}) DELETE t"

# --------------------------------------------------------------------------------------
# Expectation table — the single place to flip rows as fixes land. Cite P-ids.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Expectation:
    expect: str  # "pass" | "expected-fail"
    pids: str  # e.g. "P-012", "" when none
    note: str

    @property
    def label(self) -> str:
        if self.expect == "pass":
            return "pass"
        return f"expected-fail({self.pids})" if self.pids else "expected-fail"


EXPECTATIONS: dict[str, Expectation] = {
    "S01": Expectation(
        "pass", "P-013",
        "admin auth fail-closed on any registry state: no-token POST/GET -> 401 and the routes "
        "source contains no has_tenants gate (bootstrap bypass impossible by construction; "
        "empty-registry proof: tests/security/test_admin_auth.py).",
    ),
    "S02": Expectation("pass", "", "wrong admin token -> 401 (regression guard)."),
    "S03": Expectation("pass", "", "tenant create + list with the admin token."),
    "S04": Expectation(
        "pass", "",
        "full journey: operator bearer trusted source, memory with "
        "derived_from, action, /v1/gate allow + block, /v1/blame, /v1/impact.",
    ),
    "S05": Expectation(
        "pass", "",
        "basic revoke/reinstate statuses incl. the preserved-support case (revoked parent + healthy "
        "corroborating source -> preserved, then reinstate -> ok).",
    ),
    "S06": Expectation(
        "pass", "P-012",
        "reinstate(A) does not un-revoke independent root B: A(src)->B(mem)->Cc(mem); "
        "revoke A, revoke B, reinstate A => A=ok, B=revoked, Cc=tainted (FIXED; flip back only "
        "if it regresses).",
    ),
    "S07": Expectation(
        "pass", "P-014",
        "quota: node_cap 5 tenant, one /v1/events creating 55 nodes => want 429 quota_exceeded and "
        "NO partial write; request-wide admission rejects before mutation.",
    ),
    "S08": Expectation(
        "pass", "P-021",
        "malformed-event table (conf:5, artifacts:5, derived_from:'abc', NUL in uri) => want 422 "
        "invalid_argument, never 500; shared strict validation rejects before writing.",
    ),
    "S09": Expectation(
        "pass", "P-021",
        "no-exception-leak scan over every S08 response body (must not contain 'object is not "
        "iterable', 'Traceback', 'File \"', 'Error (').",
    ),
    "S10": Expectation("pass", "", "cross-tenant: B's token requesting A's node id -> 404."),
    "S11": Expectation(
        "pass", "",
        "oversized body (>=256KB) -> 413 too_large; forged non-numeric Content-Length -> 400.",
    ),
    "S12": Expectation(
        "pass", "P-029",
        "'Authorization: Bearer  <token>' (double space) -> 401 (fixed by strict bearer parsing; flip "
        "back only if it regresses).",
    ),
    "S13": Expectation(
        "pass", "P-029",
        "GET /metrics (no token) -> 401 (fixed); GET /docs (PEDIGREE_ENV=dev default) -> 200 under dev "
        "(disabled in production by rule; not reproduced here).",
    ),
    "S14": Expectation(
        "expected-fail", "P-022, P-029",
        "metrics content after a revoke: 200 + a 'pedigree' series; today 200 but only python_gc_*/"
        "python_info (no pedigree metric is registered). Row sends X-Admin-Token (target state).",
    ),
    "S15": Expectation(
        "pass", "P-025",
        "FALKOR_PORT=1 python -c 'import pedigree.api.app, pedigree.mcp_server' -> exit 0 (fixed: no "
        "import-time DB access; flip back to expected-fail only if it regresses).",
    ),
    "S16": Expectation(
        "pass", "P-016",
        "MCP stdio: real client against `python -m pedigree.cli mcp --transport stdio` (initialize -> "
        "pedigree_record_source -> pedigree_blame). Fixed at 6340a5c + 561b7e2: flip back to "
        "expected-fail only if it regresses.",
    ),
    "S17": Expectation(
        "pass", "P-016",
        "MCP HTTP: real streamable-HTTP client against <base_url>/mcp (initialize -> "
        "pedigree_record_source -> pedigree_blame). Fixed at 6340a5c + 561b7e2.",
    ),
    "S18": Expectation(
        "pass", "",
        "CLI subcommands `admin create-tenant` and `resume` exist (exit 0 on --help); P-011/P-013 "
        "fixed.",
    ),
    "S19": Expectation(
        "pass", "",
        "heavy: 10 batches x 150 events to ~1500 nodes, /v1/invariants clean, revoke a root with "
        ">=500 descendants in <20s (wall time reported), reinstate, invariants clean again.",
    ),
    "S20": Expectation(
        "pass", "P-020",
        "burst: exactly 120 read-only gate calls succeed then rate-limit; an independent "
        "120-write budget remains usable, with Retry-After on the next write.",
    ),
    "S21": Expectation(
        "pass", "",
        "UI: GET / -> 200 with an HTML marker; after the S16-S17 MCP checks, / and /mcp coexist "
        "(bare GET /mcp is answered by the MCP app, not 404).",
    ),
    "S22": Expectation("pass", "P-015", "agent bearer cannot revoke, reinstate or assert trusted provenance; even with global admin header."),
    "CLEAN": Expectation(
        "pass", "", "cleanup verification: every graph and registry row this run created is gone "
        "and the graph set returned to its baseline.",
    ),
}


# --------------------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    evidence: str


@dataclass
class ScenarioResult:
    skipped: str | None = None
    checks: list[Check] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, evidence: str) -> bool:
        self.checks.append(Check(name, bool(ok), evidence))
        return bool(ok)

    def note(self, text: str) -> None:
        self.info.append(text)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def summary(self) -> str:
        if self.skipped is not None:
            return f"SKIP({self.skipped})"
        if not self.checks:
            return "no checks recorded"
        failed = [c for c in self.checks if not c.ok]
        shown = failed or self.checks
        return " ; ".join(f"{c.name} -> {c.evidence}" for c in shown)[:420]


@dataclass(frozen=True)
class Tenant:
    id: str
    token: str
    operator_token: str


@dataclass
class Row:
    scenario: str
    title: str
    expectation: Expectation
    result: ScenarioResult
    outcome: str  # PASS | FAIL | EXPECTED-FAIL | STALE | SKIP


class SkipScenario(Exception):
    """Raised by a scenario to report SKIP(reason) without failing the run."""


class HarnessError(Exception):
    """Fatal harness-level problem (server cannot start, etc.)."""


# --------------------------------------------------------------------------------------
# Masking / small helpers
# --------------------------------------------------------------------------------------
def mask(text: str, extra_secrets: list[str] | None = None) -> str:
    """Mask tokens: first 6 chars + '...'. Applies to `ped_...` tokens and explicit secrets."""
    out = TOKEN_RE.sub(lambda m: m.group(0)[:6] + "...", text)
    for secret in extra_secrets or []:
        if secret and len(secret) >= 6:
            out = out.replace(secret, secret[:6] + "...")
    return out


def frag(body: Any, n: int = 160) -> str:
    """One-line body fragment for evidence."""
    try:
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=True)
    except (TypeError, ValueError):
        text = str(body)
    text = " ".join(text.split())
    return text[:n]


def err_code(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("code", ""))
    return ""


def pick_port() -> int:
    for _ in range(60):
        port = random.randint(*PORT_RANGE)
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise HarnessError(f"could not find a free port in {PORT_RANGE[0]}-{PORT_RANGE[1]}")


def parse_ts() -> tuple[str, str]:
    now_utc = datetime.now(UTC)
    return now_utc.strftime("%Y%m%dT%H%M%SZ"), now_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


# --------------------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------------------
class Ctx:
    """Shared run state: HTTP client, credentials, DB access, bookkeeping, masking."""

    def __init__(
        self,
        base: str,
        client: httpx.Client,
        admin_token: str | None,
        db: Db | None,
        mode: str,
        log_path: Path | None,
    ) -> None:
        self.base = base.rstrip("/")
        self.client = client
        self.admin_token = admin_token
        self.db = db
        self.mode = mode
        self.log_path = log_path
        self.tenants: dict[str, Tenant] = {}
        self.created_graphs: set[str] = set()
        self.created_tenants: set[str] = set()
        self.secrets: list[str] = [admin_token] if admin_token else []
        self.state: dict[str, Any] = {}
        self._registry: TenantRegistry | None = None

    # -- credentials ---------------------------------------------------------------
    @property
    def registry(self) -> TenantRegistry | None:
        if self.db is None:
            return None
        if self._registry is None:
            self._registry = TenantRegistry(self.db)
        return self._registry

    def registry_count(self) -> int:
        if self.db is None:
            raise SkipScenario("FalkorDB is not reachable from the harness")
        res = self.db.ro_query(REGISTRY_GRAPH, Q_REGISTRY_COUNT, {}, op="dogfood.registry_count")
        return int(res.result_set[0][0]) if res.result_set else 0

    def ensure_tenant(self, alias: str, node_cap: int | None = None) -> Tenant:
        tenant = self.tenants.get(alias)
        if tenant is not None:
            return tenant
        tid = "dogfood" + secrets.token_hex(4)
        body: dict[str, Any] = {"id": tid}
        if node_cap is not None:
            body["node_cap"] = node_cap
        token: str | None = None
        operator_token = ""
        path = ""
        if self.admin_token:
            resp = self.client.post("/admin/tenants", json=body, headers=self.admin_headers())
            if resp.status_code == 200:
                payload = resp.json()
                token = str(payload.get("agent_token", payload.get("token", "")))
                operator_token = str(payload.get("operator_token", ""))
                self.secrets.extend([token, operator_token])
                # Register ownership before checking credential shape, so a bad issuance
                # response cannot leak this harness's successfully created registry row.
                self.created_tenants.add(tid)
                self.created_graphs.add(graph_name(tid))
                path = "HTTP /admin/tenants"
            else:
                raise HarnessError(
                    f"tenant create failed for {tid}: {resp.status_code} {frag(resp.text)}"
                )
        elif self.registry is not None:
            cred = self.registry.create_tenant(tid, node_cap)
            self.created_tenants.add(tid)
            self.created_graphs.add(graph_name(tid))
            token = cred.token
            operator_token = cred.operator_token
            path = "direct TenantRegistry (no admin token available)"
        if not token:
            raise SkipScenario("cannot create tenants: no admin token and no DB access")
        if not operator_token:
            raise HarnessError("tenant issuance omitted the operator credential")
        self.created_tenants.add(tid)
        self.created_graphs.add(graph_name(tid))
        self.secrets.extend([token, operator_token])
        tenant = Tenant(tid, token, operator_token)
        self.tenants[alias] = tenant
        self.state.setdefault("tenant_paths", {})[tid] = path
        return tenant

    # -- HTTP helpers --------------------------------------------------------------
    def admin_headers(self) -> dict[str, str]:
        if not self.admin_token:
            return {}
        return {"X-Admin-Token": self.admin_token}

    def bearer(self, tenant: Tenant) -> dict[str, str]:
        return {"Authorization": f"Bearer {tenant.token}"}

    def tenant_headers(self, tenant: Tenant) -> dict[str, str]:
        return {"Authorization": f"Bearer {tenant.operator_token}"}

    def post(self, path: str, json_body: Any, headers: dict[str, str] | None = None,
             timeout: float | None = None) -> httpx.Response:
        return self.client.post(path, json=json_body, headers=headers, timeout=timeout)

    def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return self.client.get(path, headers=headers)

    def evidence(self, method: str, path: str, resp: httpx.Response, n: int = 160) -> str:
        return f"{method} {path} -> {resp.status_code} {frag(resp.text, n)}"

    def gname(self, tenant: Tenant) -> str:
        return graph_name(tenant.id)

    def node_count(self, tenant: Tenant) -> int | None:
        if self.db is None:
            return None
        from pedigree.db.schema import node_count

        try:
            return node_count(self.db, self.gname(tenant))
        except Exception:  # noqa: BLE001 - reporting helper must not crash a scenario
            return None


# --------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------
def s01_admin_bootstrap(ctx: Ctx, res: ScenarioResult) -> None:
    """P-013 (fixed): admin auth is fail-closed unconditionally; no bootstrap bypass exists.

    The old `has_tenants()` gate made a fresh/empty registry skip auth entirely. Non-destructive
    proof on the live (populated) registry: no-token calls 401 AND the routes source contains no
    `has_tenants` reference, so the bypass is impossible by construction; the empty-registry case
    itself is proven by `tests/security/test_admin_auth.py`
    (`test_fresh_registry_bootstrap_is_fail_closed`, monkeypatched empty registry).
    """
    tid = "dogfood" + secrets.token_hex(4)
    resp = ctx.post("/admin/tenants", json_body={"id": tid}, headers={})
    if resp.status_code == 200:  # safety: if this ever regresses, clean up after ourselves
        body = {}
        with contextlib.suppress(Exception):
            body = resp.json()
        tokens = [str(body.get(key, "")) for key in ("token", "agent_token", "operator_token")] if isinstance(body, dict) else []
        ctx.created_tenants.add(tid)
        ctx.created_graphs.add(graph_name(tid))
        ctx.secrets.extend(token for token in tokens if token)
    res.check("POST /admin/tenants (no token) -> 401", resp.status_code == 401,
              ctx.evidence("POST", "/admin/tenants", resp))
    gr = ctx.get("/admin/tenants")
    res.check("GET /admin/tenants (no token) -> 401", gr.status_code == 401,
              ctx.evidence("GET", "/admin/tenants", gr))
    src = (ROOT / "src" / "pedigree" / "api" / "routes" / "admin.py").read_text(encoding="utf-8")
    res.check("admin routes contain no has_tenants gate (bypass impossible by construction)",
              "registry.has_tenants" not in src,
              "src/pedigree/api/routes/admin.py: no registry.has_tenants call site")


def s02_wrong_admin_token(ctx: Ctx, res: ScenarioResult) -> None:
    count = ctx.registry_count()
    if count == 0:
        raise SkipScenario("registry is empty; fail-open bootstrap path (P-013) is exercised by S01")
    resp = ctx.post("/admin/tenants", json_body={"id": "dogfood" + secrets.token_hex(4)},
                    headers={"X-Admin-Token": "dogfood-wrong-admin-token"})
    res.check("POST /admin/tenants (wrong token) -> 401",
              resp.status_code == 401 and err_code(_json(resp)) == "unauthorized",
              ctx.evidence("POST", "/admin/tenants", resp))


def s03_tenant_create_list(ctx: Ctx, res: ScenarioResult) -> None:
    if not ctx.admin_token:
        raise SkipScenario("no admin token available (attach mode): admin HTTP create/list not testable")
    tenant = ctx.ensure_tenant("T_A")
    resp = ctx.get("/admin/tenants", headers=ctx.admin_headers())
    ids: list[str] = []
    with contextlib.suppress(Exception):
        ids = [t.get("id") for t in resp.json().get("tenants", [])]
    res.check("GET /admin/tenants -> 200 listing the new tenant",
              resp.status_code == 200 and tenant.id in ids,
              f"GET /admin/tenants -> {resp.status_code} (n={len(ids)}, contains={tenant.id in ids})")
    res.note(f"tenant {tenant.id} created via {ctx.state.get('tenant_paths', {}).get(tenant.id, '?')}")


def s04_full_journey(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_A")
    tag = secrets.token_hex(3)
    src_id, mem_id, act_id = f"dsrc_{tag}", f"dmem_{tag}", f"dact_{tag}"
    events = [
        # Explicit integrity=trusted needs operator; ordinary agent file captures are untrusted.
        {"type": "source", "kind": "file", "id": src_id, "uri": f"file:///dogfood/{tag}.md",
         "title": "dogfood design doc", "integrity": "trusted"},
        {"type": "memory", "id": mem_id, "text": "dogfood memory",
         "derived_from": [src_id]},
        {"type": "action", "id": act_id, "tool": "Read", "summary": "read the design doc",
         "relied_on": [mem_id], "effect": "reversible", "risk": "low"},
    ]
    resp = ctx.post("/v1/events",
                    {"runtime": "generic", "events": events},
                    headers=ctx.tenant_headers(tenant))
    body = _json(resp)
    created = body.get("created", []) if isinstance(body, dict) else []
    res.check("POST /v1/events (source+memory+action) -> 200",
              resp.status_code == 200 and set(created) == {src_id, mem_id, act_id},
              ctx.evidence("POST", "/v1/events", resp))
    res.note("operator bearer exercised: source kind 'file', integrity trusted")

    blame = ctx.get(f"/v1/blame/{mem_id}", headers=ctx.bearer(tenant))
    bnode = _json(blame).get("node", {}) if isinstance(_json(blame), dict) else {}
    res.check("GET /v1/blame -> 200, memory ok",
              blame.status_code == 200 and bnode.get("status") == "ok" and bnode.get("id") == mem_id,
              ctx.evidence("GET", f"/v1/blame/{mem_id}", blame))
    graph_nodes = _json(blame).get("graph", {}).get("nodes", []) if isinstance(_json(blame), dict) else []
    src_flags = [n.get("low_integrity") for n in graph_nodes if n.get("id") == src_id]
    res.check("operator source recorded as trusted (low_integrity false)",
              src_flags == [False], f"blame graph low_integrity for {src_id}: {src_flags}")

    allow = ctx.post("/v1/gate",
                     {"action": {"tool": "Read", "summary": "read the design doc",
                                 "effect": "reversible", "risk": "low"},
                      "relied_on": [mem_id]},
                     headers=ctx.bearer(tenant))
    allow_body = _json(allow)
    res.check("POST /v1/gate allow case -> decision allow",
              allow.status_code == 200 and allow_body.get("decision") == "allow",
              ctx.evidence("POST", "/v1/gate", allow))

    impact = ctx.get(f"/v1/impact/{src_id}", headers=ctx.bearer(tenant))
    ibody = _json(impact)
    n_total = ibody.get("counts", {}).get("n_total") if isinstance(ibody, dict) else None
    # source -> memory -> action: exactly 2 descendants (impact excludes the node itself)
    res.check("GET /v1/impact(source) -> 200, >=2 descendants",
              impact.status_code == 200 and isinstance(n_total, int) and n_total >= 2,
              ctx.evidence("GET", f"/v1/impact/{src_id}", impact))

    revoke = ctx.post("/v1/revoke", {"root_id": src_id, "reason": "dogfood journey"},
                      headers=ctx.tenant_headers(tenant))
    rbody = _json(revoke)
    tainted = rbody.get("counts", {}).get("tainted") if isinstance(rbody, dict) else None
    res.check("POST /v1/revoke(source) -> 200 with tainted descendants",
              revoke.status_code == 200 and isinstance(tainted, int) and tainted >= 1,
              ctx.evidence("POST", "/v1/revoke", revoke))

    blame2 = ctx.get(f"/v1/blame/{mem_id}", headers=ctx.bearer(tenant))
    b2 = _json(blame2) if isinstance(_json(blame2), dict) else {}
    roots = [r.get("id") for r in b2.get("roots", [])]
    res.check("GET /v1/blame -> memory tainted with the revoked source as root",
              blame2.status_code == 200 and b2.get("node", {}).get("status") == "tainted"
              and src_id in roots,
              ctx.evidence("GET", f"/v1/blame/{mem_id}", blame2))

    block = ctx.post("/v1/gate",
                     {"action": {"tool": "Bash", "summary": "git push origin main",
                                 "effect": "irreversible", "risk": "high"},
                      "relied_on": [mem_id]},
                     headers=ctx.bearer(tenant))
    block_body = _json(block)
    hook_decision = (block_body.get("hook", {}).get("hookSpecificOutput", {}) or {}).get(
        "permissionDecision") if isinstance(block_body, dict) else None
    res.check("POST /v1/gate block case -> decision block + hook deny",
              block.status_code == 200 and block_body.get("decision") == "block"
              and hook_decision == "deny",
              ctx.evidence("POST", "/v1/gate", block))


def s05_revoke_reinstate(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_R")
    tag = secrets.token_hex(3)
    src1, src2 = f"rsrc_a{tag}", f"rsrc_b{tag}"
    mem1, mem2 = f"rmem_t{tag}", f"rmem_p{tag}"
    events = [
        {"type": "source", "kind": "web", "id": src1, "uri": f"https://dogfood.test/{tag}/a"},
        {"type": "source", "kind": "web", "id": src2, "uri": f"https://dogfood.test/{tag}/b"},
        {"type": "memory", "id": mem1, "text": "tainted branch", "derived_from": [src1]},
        {"type": "memory", "id": mem2, "text": "preserved branch", "derived_from": [src1],
         "corroborated_by": [src2]},
    ]
    resp = ctx.post("/v1/events", {"runtime": "generic", "events": events},
                    headers=ctx.bearer(tenant))
    res.check("POST /v1/events (4 nodes, one corroborated) -> 200",
              resp.status_code == 200, ctx.evidence("POST", "/v1/events", resp))

    attestation = ctx.post("/v1/corroborate", {"memory_id": mem2, "source_id": src2, "by": "human"},
                           headers=ctx.tenant_headers(tenant))
    res.check("operator attests the preserved branch", attestation.status_code == 200,
              ctx.evidence("POST", "/v1/corroborate", attestation))

    revoke = ctx.post("/v1/revoke", {"root_id": src1, "reason": "dogfood"},
                      headers=ctx.tenant_headers(tenant))
    stats = ctx.get("/v1/stats", headers=ctx.bearer(tenant))
    by_status = _json(stats).get("by_status", {}) if isinstance(_json(stats), dict) else {}
    want = {"ok": 1, "revoked": 1, "tainted": 1, "preserved": 1}
    res.check("after revoke: statuses ok/revoked/tainted/preserved = 1/1/1/1",
              revoke.status_code == 200 and all(by_status.get(k, 0) == v for k, v in want.items()),
              f"POST /v1/revoke -> {revoke.status_code}; GET /v1/stats -> {frag(by_status)}")

    reinstate = ctx.post("/v1/reinstate", {"root_id": src1}, headers=ctx.tenant_headers(tenant))
    stats2 = ctx.get("/v1/stats", headers=ctx.bearer(tenant))
    by2 = _json(stats2).get("by_status", {}) if isinstance(_json(stats2), dict) else {}
    res.check("after reinstate: all 4 nodes ok again",
              reinstate.status_code == 200 and by2.get("ok", 0) == 4,
              f"POST /v1/reinstate -> {reinstate.status_code}; GET /v1/stats -> {frag(by2)}")


def s06_reinstate_independent_root(ctx: Ctx, res: ScenarioResult) -> None:
    """P-012 deterministic repro: A(source)->B(memory)->Cc(memory)."""
    tenant = ctx.ensure_tenant("T_R2")
    tag = secrets.token_hex(3)
    a, b, c = f"pa_{tag}", f"pb_{tag}", f"pc_{tag}"
    events = [
        {"type": "source", "kind": "web", "id": a, "uri": f"https://dogfood.test/{tag}/p"},
        {"type": "memory", "id": b, "text": "b", "derived_from": [a]},
        {"type": "memory", "id": c, "text": "c", "derived_from": [b]},
    ]
    created = ctx.post("/v1/events", {"runtime": "generic", "events": events},
                       headers=ctx.bearer(tenant))
    rev_a = ctx.post("/v1/revoke", {"root_id": a, "reason": "dogfood A"},
                     headers=ctx.tenant_headers(tenant))
    rev_b = ctx.post("/v1/revoke", {"root_id": b, "reason": "dogfood B"},
                     headers=ctx.tenant_headers(tenant))
    rein_a = ctx.post("/v1/reinstate", {"root_id": a}, headers=ctx.tenant_headers(tenant))
    stats = ctx.get("/v1/stats", headers=ctx.bearer(tenant))
    by_status = _json(stats).get("by_status", {}) if isinstance(_json(stats), dict) else {}
    rbody = _json(rein_a)
    remaining = rbody.get("remaining_roots") if isinstance(rbody, dict) else None
    res.check("setup: events + revoke A + revoke B all 200",
              created.status_code == 200 and rev_a.status_code == 200 and rev_b.status_code == 200,
              f"events {created.status_code}; revoke A {rev_a.status_code}; revoke B {rev_b.status_code}")
    res.check("reinstate(A): B stays revoked, Cc tainted (want ok=1 revoked=1 tainted=1)",
              by_status.get("ok") == 1 and by_status.get("revoked") == 1
              and by_status.get("tainted") == 1,
              f"GET /v1/stats -> {frag(by_status)}")
    res.check("reinstate(A) response: remaining_roots == 1",
              remaining == 1, f"POST /v1/reinstate -> {frag(rbody)}")


def s07_quota(ctx: Ctx, res: ScenarioResult) -> None:
    """P-014: quota overflow must reject the whole batch before any mutation."""
    if not ctx.admin_token:
        raise SkipScenario("node_cap 5 needs POST /admin/tenants with the admin token")
    tenant = ctx.ensure_tenant("T_Q", node_cap=5)
    tag = secrets.token_hex(3)
    events = [{"type": "source", "kind": "web", "id": f"qsrc_{tag}",
               "uri": f"https://dogfood.test/{tag}/q"}]
    events += [{"type": "memory", "id": f"qmem_{tag}_{i:03d}", "text": f"m{i}",
                "derived_from": [f"qsrc_{tag}"]} for i in range(54)]
    resp = ctx.post("/v1/events", {"runtime": "generic", "events": events},
                    headers=ctx.bearer(tenant))
    body = _json(resp)
    created = body.get("created", []) if isinstance(body, dict) else []
    count = ctx.node_count(tenant)
    write_ok = (resp.status_code == 429 and err_code(body) == "quota_exceeded"
                and (count in (0, None)))
    res.check("55-node batch on a cap-5 tenant -> 429 quota_exceeded, no nodes written",
              write_ok,
              f"POST /v1/events -> {resp.status_code} {frag(body, 90)}; created={len(created)}; "
              f"graph nodes={count}")


def s08_malformed_events(ctx: Ctx, res: ScenarioResult) -> None:
    """P-021: every malformed event shape -> 422 invalid_argument, never 500."""
    tenant = ctx.ensure_tenant("T_S")
    cases: list[tuple[str, dict[str, Any]]] = [
        ("conf:5 on a source",
         {"type": "source", "kind": "web", "uri": "https://dogfood.test/conf", "conf": 5}),
        ("artifacts:5 on an action",
         {"type": "action", "tool": "T", "summary": "s", "artifacts": 5}),
        ("derived_from:'abc' on a memory",
         {"type": "memory", "text": "m", "derived_from": "abc"}),
        ("NUL in source uri",
         {"type": "source", "kind": "web", "uri": "https://dogfood.test/nul\x00x"}),
    ]
    responses: list[tuple[str, int, str]] = []
    for name, event in cases:
        resp = ctx.post("/v1/events", {"runtime": "generic", "events": [event]},
                        headers=ctx.bearer(tenant))
        body = _json(resp)
        strict = resp.status_code == 422 and err_code(body) == "invalid_argument"
        responses.append((name, resp.status_code, resp.text))
        res.check(f"{name} -> 422 invalid_argument",
                  strict,
                  ctx.evidence("POST", "/v1/events", resp))
    ctx.state["s08_responses"] = responses


def s09_no_exception_leak(ctx: Ctx, res: ScenarioResult) -> None:
    """P-021: no S08 response body may leak a Python exception string."""
    responses: list[tuple[str, int, str]] = ctx.state.get("s08_responses", [])
    if not responses:
        raise SkipScenario("S08 recorded no responses (scenario order changed?)")
    markers = ["object is not iterable", "Traceback", 'File "', "Error ("]
    leaked: list[str] = []
    for name, _status, text in responses:
        hits = [m for m in markers if m in text]
        if hits:
            leaked.append(f"{name}: {hits}")
    res.check("no exception-leak markers in any S08 response body",
              not leaked,
              "clean" if not leaked else "; ".join(leaked)[:280])


def s10_cross_tenant(ctx: Ctx, res: ScenarioResult) -> None:
    tenant_a = ctx.ensure_tenant("T_C1")
    tenant_b = ctx.ensure_tenant("T_C2")
    node = f"csrc_{secrets.token_hex(3)}"
    made = ctx.post("/v1/events",
                    {"runtime": "generic",
                     "events": [{"type": "source", "kind": "web", "id": node,
                                 "uri": f"https://dogfood.test/iso/{node}"}]},
                    headers=ctx.bearer(tenant_a))
    res.check("setup: node created in tenant A", made.status_code == 200,
              ctx.evidence("POST", "/v1/events", made))
    blame = ctx.get(f"/v1/blame/{node}", headers=ctx.bearer(tenant_b))
    impact = ctx.get(f"/v1/impact/{node}", headers=ctx.bearer(tenant_b))
    res.check("tenant B /v1/blame of A's node -> 404 not_in_graph",
              blame.status_code == 404 and err_code(_json(blame)) == "not_in_graph",
              ctx.evidence("GET", f"/v1/blame/{node}", blame))
    res.check("tenant B /v1/impact of A's node -> 404 not_in_graph",
              impact.status_code == 404 and err_code(_json(impact)) == "not_in_graph",
              ctx.evidence("GET", f"/v1/impact/{node}", impact))


def s11_body_limits(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_C2")
    big = "x" * (300 * 1024)
    resp = ctx.post("/v1/gate",
                    {"action": {"tool": "Read", "summary": "big", "effect": "reversible",
                                "risk": "low"}, "relied_on": [big]},
                    headers=ctx.bearer(tenant), timeout=120.0)
    thin = ctx.post("/v1/gate",
                    {"action": {"tool": "Read", "summary": "thin", "effect": "reversible",
                                "risk": "low"}},
                    headers=ctx.bearer(tenant))
    res.check("oversized body (>=256KB) -> 413 too_large",
              resp.status_code == 413 and err_code(_json(resp)) == "too_large",
              ctx.evidence("POST", "/v1/gate (300KB)", resp))
    res.check("control: normal body -> 200", thin.status_code == 200,
              ctx.evidence("POST", "/v1/gate", thin, 80))

    status, raw = _raw_request(ctx.base, b"POST /v1/gate HTTP/1.1\r\nHost: dogfood\r\n"
                                          b"Content-Type: application/json\r\n"
                                          b"Content-Length: abc\r\nConnection: close\r\n\r\n")
    res.check("forged non-numeric Content-Length -> 400", status == 400,
              f"raw socket -> {status} {frag(raw.decode('utf-8', 'replace'), 90)}")


def s12_double_space_bearer(ctx: Ctx, res: ScenarioResult) -> None:
    """P-029: 'Bearer  <token>' (two spaces) must be 401."""
    tenant = ctx.ensure_tenant("T_C1")
    control = ctx.get("/v1/stats", headers=ctx.bearer(tenant))
    forged = ctx.get("/v1/stats", headers={"Authorization": f"Bearer  {tenant.token}"})
    res.check("control: single-space Bearer -> 200", control.status_code == 200,
              ctx.evidence("GET", "/v1/stats", control, 60))
    res.check("double-space Bearer -> 401", forged.status_code == 401,
              ctx.evidence("GET", "/v1/stats (Bearer double-space)", forged))


def s13_metrics_docs_protection(ctx: Ctx, res: ScenarioResult) -> None:
    """P-029: /metrics behind deployment admin auth, docs visibility follows settings."""
    metrics = ctx.get("/metrics")
    docs = ctx.get("/docs")
    openapi = ctx.get("/openapi.json")
    res.check("GET /metrics (no token) -> 401", metrics.status_code == 401,
              ctx.evidence("GET", "/metrics", metrics, 90))
    res.check("GET /docs (PEDIGREE_ENV=dev default) -> 200", docs.status_code == 200,
              ctx.evidence("GET", "/docs", docs, 90))
    res.note(f"informational: GET /openapi.json -> {openapi.status_code} ({len(openapi.text)} bytes)")


def s14_metrics_content(ctx: Ctx, res: ScenarioResult) -> None:
    """P-022/P-029: after a revoke, /metrics must expose pedigree series."""
    headers = ctx.admin_headers()
    resp = ctx.get("/metrics", headers=headers)
    has_pedigree = "pedigree" in resp.text
    sample = [ln for ln in resp.text.splitlines() if ln and not ln.startswith("#")][:2]
    res.check("GET /metrics -> 200 with a 'pedigree' series",
              resp.status_code == 200 and has_pedigree,
              f"GET /metrics -> {resp.status_code}; pedigree={has_pedigree}; sample={frag(sample, 90)}")
    res.note("row uses deployment-admin authentication; metric instrumentation is tracked by P-022")


def s15_import_without_db(ctx: Ctx, res: ScenarioResult) -> None:
    """P-025: importing the app must not connect to the DB."""
    env = {**os.environ, "FALKOR_PORT": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", "import pedigree.api.app, pedigree.mcp_server"],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120,
    )
    tail = " | ".join(line for line in proc.stderr.strip().splitlines()[-2:])
    res.check("FALKOR_PORT=1 import pedigree.api.app, pedigree.mcp_server -> exit 0",
              proc.returncode == 0,
              f"rc={proc.returncode} stderr: {frag(tail, 150)}")


def _mcp_env(ctx: Ctx, tenant: Tenant) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PEDIGREE_", "FALKOR_"))}
    env.update({
        "PEDIGREE_MCP_TENANT": tenant.id,
        "PEDIGREE_MCP_TOKEN": tenant.token,
        "PYTHONUTF8": "1",
    })
    return env


def s16_mcp_stdio(ctx: Ctx, res: ScenarioResult) -> None:
    """P-016: real MCP stdio client journey (fixed at 6340a5c + 561b7e2)."""
    tenant = ctx.ensure_tenant("T_M")
    env = _mcp_env(ctx, tenant)
    cmd = [sys.executable, "-m", "pedigree.cli", "mcp", "--transport", "stdio"]
    alive = True
    preflight = "alive after 3s"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env, cwd=str(ROOT))
    try:
        time.sleep(3)
        rc = proc.poll()
        if rc is not None:
            alive = False
            _, err = proc.communicate(timeout=5)
            tail = " | ".join((err or "").strip().splitlines()[-3:])
            preflight = f"exited early rc={rc} stderr: {frag(tail, 150)}"
    finally:
        if proc.poll() is None:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.communicate(timeout=5)
    res.check("CLI pre-flight: `mcp --transport stdio` stays alive (stdin open)", alive, preflight)

    uri = f"https://dogfood.test/mcp-stdio/{secrets.token_hex(3)}"

    async def journey() -> dict[str, Any]:
        params = StdioServerParameters(command=sys.executable, args=cmd[1:], env=env, cwd=str(ROOT))
        out: dict[str, Any] = {}
        async with Client(params, read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            out["tools"] = [t.name for t in tools.tools]
            recorded = await client.call_tool(
                "pedigree_record_source",
                {"tenant_id": tenant.id, "token": tenant.token, "kind": "web", "uri": uri})
            out["recorded"] = json.loads(recorded.content[0].text)
            node_id = out["recorded"].get("result", {}).get("id", "")
            res.note(f"stdio recorded node {node_id}")
            blamed = await client.call_tool(
                "pedigree_blame",
                {"tenant_id": tenant.id, "token": tenant.token, "node_id": node_id})
            out["blamed"] = json.loads(blamed.content[0].text)
        return out

    try:
        out = asyncio.run(asyncio.wait_for(journey(), timeout=90))
    except Exception as exc:  # noqa: BLE001 - evidence, not a crash
        res.check("MCP stdio journey: initialize + record_source + blame", False,
                  f"{type(exc).__name__}: {frag(str(exc), 180)}")
        return
    tools = out.get("tools", [])
    rec = out.get("recorded", {})
    blame = out.get("blamed", {})
    node_id = rec.get("result", {}).get("id") if isinstance(rec, dict) else None
    res.check("stdio: tools listed incl. pedigree_record_source",
              "pedigree_record_source" in tools, f"tools={frag(tools, 120)}")
    res.check("stdio: pedigree_record_source -> ok",
              bool(rec.get("ok")) and bool(node_id), f"payload={frag(rec, 120)}")
    res.check("stdio: pedigree_blame -> ok",
              bool(blame.get("ok")) and (blame.get("result", {}) or {}).get("node", {}).get("id") == node_id,
              f"payload={frag(blame, 120)}")


def s17_mcp_http(ctx: Ctx, res: ScenarioResult) -> None:
    """P-016: real MCP streamable-HTTP client against <base_url>/mcp."""
    tenant = ctx.ensure_tenant("T_M")
    uri = f"https://dogfood.test/mcp-http/{secrets.token_hex(3)}"

    async def journey() -> dict[str, Any]:
        out: dict[str, Any] = {}
        async with Client(f"{ctx.base}/mcp", read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            out["tools"] = [t.name for t in tools.tools]
            recorded = await client.call_tool(
                "pedigree_record_source",
                {"tenant_id": tenant.id, "token": tenant.token, "kind": "web", "uri": uri})
            out["recorded"] = json.loads(recorded.content[0].text)
            node_id = out["recorded"].get("result", {}).get("id", "")
            blamed = await client.call_tool(
                "pedigree_blame",
                {"tenant_id": tenant.id, "token": tenant.token, "node_id": node_id})
            out["blamed"] = json.loads(blamed.content[0].text)
        return out

    try:
        out = asyncio.run(asyncio.wait_for(journey(), timeout=90))
    except Exception as exc:  # noqa: BLE001 - evidence, not a crash
        res.check("MCP HTTP journey: initialize + record_source + blame", False,
                  f"{type(exc).__name__}: {frag(str(exc), 180)}")
        return
    rec = out.get("recorded", {})
    blame = out.get("blamed", {})
    node_id = rec.get("result", {}).get("id") if isinstance(rec, dict) else None
    res.check("http: /mcp lists tools incl. pedigree_record_source",
              "pedigree_record_source" in out.get("tools", []),
              f"tools={frag(out.get('tools', []), 120)}")
    res.check("http: pedigree_record_source -> ok",
              bool(rec.get("ok")) and bool(node_id), f"payload={frag(rec, 120)}")
    res.check("http: pedigree_blame -> ok",
              bool(blame.get("ok")) and (blame.get("result", {}) or {}).get("node", {}).get("id") == node_id,
              f"payload={frag(blame, 120)}")


def s18_cli_subcommands(ctx: Ctx, res: ScenarioResult) -> None:
    """P-013/P-011: `pedigree admin create-tenant` and `pedigree resume` must exist."""
    for argv, name in ((["admin", "--help"], "admin"), (["resume", "--help"], "resume")):
        proc = subprocess.run([sys.executable, "-m", "pedigree.cli", *argv],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        first = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
        res.check(f"`pedigree {name} --help` -> exit 0", proc.returncode == 0,
                  f"rc={proc.returncode} {frag(first, 110)}")


def s19_heavy(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_H")
    tag = secrets.token_hex(3)
    root = f"hsrc_{tag}"
    chain = root
    batches: list[list[dict[str, Any]]] = []
    for batch in range(10):
        events = []
        for i in range(150):
            node = f"hmem_{tag}_{batch:02d}{i:03d}"
            events.append({"type": "memory", "id": node, "text": f"m{batch}-{i}",
                           "derived_from": [chain]})
            chain = node
        batches.append(events)

    first = ctx.post("/v1/events",
                     {"runtime": "generic",
                      "events": [{"type": "source", "kind": "web", "id": root,
                                  "uri": f"https://dogfood.test/heavy/{tag}"}]},
                     headers=ctx.bearer(tenant), timeout=120.0)
    bad_batches: list[str] = []
    for idx, events in enumerate(batches):
        resp = ctx.post("/v1/events", {"runtime": "generic", "events": events},
                        headers=ctx.bearer(tenant), timeout=120.0)
        if resp.status_code != 200:
            bad_batches.append(f"batch {idx} -> {resp.status_code}")
    count = ctx.node_count(tenant)
    res.check("10 batches x 150 events ingested (200 each)",
              first.status_code == 200 and not bad_batches,
              f"source {first.status_code}; batches_ok={len(batches) - len(bad_batches)}/10"
              + (f"; {frag('; '.join(bad_batches), 120)}" if bad_batches else "")
              + f"; graph nodes={count}")
    res.note(f"heavy graph builds ~1501 nodes (root + 1500 memories); measured graph nodes={count}")

    inv0 = ctx.get("/v1/invariants", headers=ctx.bearer(tenant))
    v0 = _json(inv0).get("violations", []) if isinstance(_json(inv0), dict) else ["unparseable"]
    res.check("pre-revoke invariants clean", inv0.status_code == 200 and v0 == [],
              ctx.evidence("GET", "/v1/invariants", inv0, 90))

    t0 = time.perf_counter()
    revoke = ctx.post("/v1/revoke", {"root_id": root, "reason": "dogfood heavy"},
                      headers=ctx.tenant_headers(tenant), timeout=120.0)
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    rbody = _json(revoke)
    tainted = rbody.get("counts", {}).get("tainted") if isinstance(rbody, dict) else None
    server_ms = rbody.get("ms") if isinstance(rbody, dict) else None
    res.check("revoke >=500 descendants -> 200", revoke.status_code == 200
              and isinstance(tainted, int) and tainted >= 500,
              f"POST /v1/revoke -> {revoke.status_code} tainted={tainted} "
              f"(server {server_ms} ms, wall {wall_ms} ms)")
    res.check("revoke wall time < 20000 ms", wall_ms < 20_000,
              f"wall {wall_ms} ms (server-reported {server_ms} ms, {tainted} tainted)")

    inv1 = ctx.get("/v1/invariants", headers=ctx.bearer(tenant))
    v1 = _json(inv1).get("violations", []) if isinstance(_json(inv1), dict) else ["unparseable"]
    res.check("post-revoke invariants clean", inv1.status_code == 200 and v1 == [],
              ctx.evidence("GET", "/v1/invariants", inv1, 90))

    reinstate = ctx.post("/v1/reinstate", {"root_id": root},
                         headers=ctx.tenant_headers(tenant), timeout=120.0)
    inv2 = ctx.get("/v1/invariants", headers=ctx.bearer(tenant))
    v2 = _json(inv2).get("violations", []) if isinstance(_json(inv2), dict) else ["unparseable"]
    res.check("reinstate -> 200 and invariants clean again",
              reinstate.status_code == 200 and inv2.status_code == 200 and v2 == [],
              f"POST /v1/reinstate -> {reinstate.status_code} {frag(_json(reinstate), 70)}; "
              f"violations={frag(v2, 60)}")


def s20_burst_gate(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_B")
    body = {"action": {"tool": "Read", "summary": "burst", "effect": "reversible", "risk": "low"}}
    statuses: list[int] = []
    first_429: int | None = None
    for i in range(150):
        resp = ctx.post("/v1/gate", body, headers=ctx.bearer(tenant))
        statuses.append(resp.status_code)
        if first_429 is None and resp.status_code == 429:
            first_429 = i + 1
    unexpected = sorted({s for s in statuses if s not in (200, 429)})
    health = ctx.get("/healthz")
    res.check("read budget: exactly 120 gate calls succeed, then 30 rate limits",
              not unexpected and statuses == [200] * 120 + [429] * 30,
              f"statuses: 200x{statuses.count(200)}, 429x{statuses.count(429)}"
              + (f", unexpected={unexpected}" if unexpected else ""))
    res.check("server responsive after the burst", health.status_code == 200,
              ctx.evidence("GET", "/healthz", health, 60))
    write_statuses = [ctx.post("/v1/sessions", {"session_id": "dogfood_rate_session"},
                              headers=ctx.bearer(tenant)).status_code for _ in range(120)]
    limited = ctx.post("/v1/sessions", {"session_id": "dogfood_rate_session"}, headers=ctx.bearer(tenant))
    res.check("independent write budget: 120 admitted writes, then 429 with Retry-After",
              write_statuses == [200] * 120 and limited.status_code == 429
              and err_code(_json(limited)) == "rate_limited"
              and limited.headers.get("Retry-After", "").isdigit(),
              f"writes 200x{write_statuses.count(200)}; next={limited.status_code}; "
              f"retry_after={limited.headers.get('Retry-After')}")
    res.note(f"first read 429 at call {first_429}; repeated Session writes create only one fixture node")


def s21_ui_and_mcp_coexist(ctx: Ctx, res: ScenarioResult) -> None:
    ui = ctx.get("/")
    mcp = ctx.get("/mcp")
    body = mcp.text.lower()
    res.check("GET / -> 200 with the UI marker", ui.status_code == 200 and UI_MARKER in ui.text,
              f"GET / -> {ui.status_code} marker={UI_MARKER in ui.text}",)
    res.check("/mcp is served (not 404) next to / (S16-S17 already used it)",
              mcp.status_code != 404 and ("session" in body or "jsonrpc" in body),
              ctx.evidence("GET", "/mcp", mcp, 110))


def s22_agent_role_denials(ctx: Ctx, res: ScenarioResult) -> None:
    tenant = ctx.ensure_tenant("T_ROLE")
    tag = secrets.token_hex(3)
    sid, mid = f"rolesrc_{tag}", f"rolemem_{tag}"
    setup = ctx.post("/v1/events", {"runtime": "generic", "events": [
        {"type": "source", "kind": "web", "id": sid},
        {"type": "memory", "id": mid, "text": "role guard", "derived_from": [sid]},
    ]}, headers=ctx.bearer(tenant))
    res.check("agent can ingest baseline graph", setup.status_code == 200,
              ctx.evidence("POST", "/v1/events", setup))
    before = ctx.node_count(tenant)
    attempts = [
        ("/v1/revoke", {"root_id": sid, "reason": "agent escalation"}),
        ("/v1/reinstate", {"root_id": sid}),
        ("/v1/corroborate", {"memory_id": mid, "source_id": sid, "by": "human"}),
        ("/v1/sources", {"kind": "web", "integrity": "trusted"}),
        ("/v1/events", {"runtime": "generic", "session_id": f"rolesess_{tag}", "events": [
            {"type": "session"}, {"type": "source", "kind": "web", "integrity": "trusted"}]}),
    ]
    # A valid deployment-admin header must not upgrade an agent bearer.
    headers = {**ctx.bearer(tenant), **ctx.admin_headers()}
    for path, payload in attempts:
        response = ctx.post(path, payload, headers=headers)
        res.check(f"agent denied {path}", response.status_code == 403
                  and err_code(_json(response)) == "forbidden", ctx.evidence("POST", path, response))
    after = ctx.node_count(tenant)
    blame = ctx.get(f"/v1/blame/{mid}", headers=ctx.bearer(tenant))
    res.check("denials leave graph size and memory status unchanged",
              before == after == 2 and _json(blame).get("node", {}).get("status") == "ok",
              f"node counts before={before} after={after}; memory={_json(blame).get('node', {}).get('status')}")


def clean_verify(ctx: Ctx, res: ScenarioResult) -> None:
    """Pseudo-scenario: cleanup verification, filled by the runner."""
    outcome = ctx.state.get("cleanup", {})
    leftover_graphs = outcome.get("leftover_graphs", ["<cleanup did not run>"])
    leftover_rows = outcome.get("leftover_rows", ["<cleanup did not run>"])
    res.check("every created graph deleted", not leftover_graphs,
              f"leftover: {leftover_graphs}" if leftover_graphs else "0 leftovers")
    res.check("every created registry row deleted", not leftover_rows,
              f"leftover: {leftover_rows}" if leftover_rows else "0 leftovers")


SCENARIO_FUNCS: dict[str, Callable[[Ctx, ScenarioResult], None]] = {
    "S01": s01_admin_bootstrap,
    "S02": s02_wrong_admin_token,
    "S03": s03_tenant_create_list,
    "S04": s04_full_journey,
    "S05": s05_revoke_reinstate,
    "S06": s06_reinstate_independent_root,
    "S07": s07_quota,
    "S08": s08_malformed_events,
    "S09": s09_no_exception_leak,
    "S10": s10_cross_tenant,
    "S11": s11_body_limits,
    "S12": s12_double_space_bearer,
    "S13": s13_metrics_docs_protection,
    "S14": s14_metrics_content,
    "S15": s15_import_without_db,
    "S16": s16_mcp_stdio,
    "S17": s17_mcp_http,
    "S18": s18_cli_subcommands,
    "S19": s19_heavy,
    "S20": s20_burst_gate,
    "S21": s21_ui_and_mcp_coexist,
    "S22": s22_agent_role_denials,
    "CLEAN": clean_verify,
}

#: Run order: S16/S17 before S21 (S21 re-checks coexistence), S18-S20 (process/load/scale) last.
RUN_ORDER: list[str] = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S11",
    "S12", "S13", "S14", "S15", "S16", "S17", "S21", "S22", "S18", "S19", "S20",
]

SCENARIO_TITLES: dict[str, str] = {
    "S01": "admin bootstrap (no token -> 401)",
    "S02": "wrong admin token",
    "S03": "tenant create + list",
    "S04": "full journey (events/gate/blame/impact)",
    "S05": "revoke + reinstate statuses",
    "S06": "reinstate vs independent revoke root",
    "S07": "quota on /v1/events",
    "S08": "malformed events -> 422",
    "S09": "no exception leaks",
    "S10": "cross-tenant isolation",
    "S11": "body size limits",
    "S12": "double-space Bearer",
    "S13": "/metrics + /docs protection",
    "S14": "metrics content after a revoke",
    "S15": "import without a DB",
    "S16": "MCP stdio journey",
    "S17": "MCP HTTP journey",
    "S18": "CLI admin/resume subcommands",
    "S19": "heavy graph + revoke latency",
    "S20": "burst 150 gate calls",
    "S21": "UI + /mcp coexistence",
    "S22": "agent role escalation denied",
    "CLEAN": "cleanup verification",
}


# --------------------------------------------------------------------------------------
# Helpers that need no context
# --------------------------------------------------------------------------------------
def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 - non-JSON bodies are evidence, not errors
        return {}


def _raw_request(base: str, request: bytes) -> tuple[int, bytes]:
    """Send raw bytes (for a forged Content-Length) and return (status, first bytes)."""
    parts = urlsplit(base)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 80
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(request)
        chunks: list[bytes] = []
        total = 0
        with contextlib.suppress(Exception):
            while total < 8192:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
                total += len(data)
    raw = b"".join(chunks)
    status = 0
    if raw.startswith(b"HTTP/"):
        with contextlib.suppress(Exception):
            status = int(raw.split(b" ", 2)[1])
    return status, raw


def log_tail(log_path: Path | None, n: int = 1500) -> str:
    if log_path is None or not log_path.exists():
        return "<no log>"
    with contextlib.suppress(Exception):
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return text[-n:]
    return "<unreadable log>"


def wait_ready(base: str, proc: subprocess.Popen, log_path: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=3.0) as client:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise HarnessError(
                    f"server exited early rc={proc.returncode}; log tail: {log_tail(log_path)}")
            try:
                if (client.get(f"{base}/healthz").status_code == 200
                        and client.get(f"{base}/readyz").status_code == 200):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
    raise HarnessError(f"server not ready within {timeout}s; log tail: {log_tail(log_path)}")


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    with contextlib.suppress(Exception):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


def git_state() -> tuple[str, str]:
    def run(args: list[str]) -> str:
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(ROOT),
                                 timeout=30)
            return out.stdout.strip() if out.returncode == 0 else "<git error>"
        except Exception:  # noqa: BLE001
            return "<git unavailable>"

    head = run(["rev-parse", "--short", "HEAD"])
    status = run(["status", "--porcelain"])
    return head, status or "<clean>"


# --------------------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------------------
def do_cleanup(db: Db | None, created_graphs: set[str], created_tenants: set[str],
               baseline_graphs: set[str]) -> dict[str, Any]:
    """Delete exactly the graphs/rows this run created, then verify. Never enumerates tenants."""
    out: dict[str, Any] = {"graphs_deleted": [], "graphs_absent": [], "rows_deleted": [],
                           "rows_leftover": [], "leftover_graphs": [], "leftover_rows": [],
                           "errors": []}
    if db is None:
        out["skipped"] = "FalkorDB not reachable from the harness"
        out["leftover_graphs"] = sorted(created_graphs)
        out["leftover_rows"] = sorted(created_tenants)
        return out
    try:
        present = set(db.list_graphs())
    except Exception as exc:  # noqa: BLE001
        out["skipped"] = f"list_graphs failed: {type(exc).__name__}"
        return out
    for gname in sorted(created_graphs):
        if gname not in present:
            out["graphs_absent"].append(gname)
            continue
        try:
            db.select(gname).delete()
            out["graphs_deleted"].append(gname)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"delete graph {gname}: {type(exc).__name__}")
    for tid in sorted(created_tenants):
        try:
            db.query(REGISTRY_GRAPH, Q_REGISTRY_DELETE, {"id": tid}, op="dogfood.cleanup")
            rows = db.ro_query(REGISTRY_GRAPH, Q_REGISTRY_EXISTS, {"id": tid},
                               op="dogfood.cleanup.verify").result_set or []
            (out["rows_deleted"] if not rows else out["rows_leftover"]).append(tid)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"delete registry row {tid}: {type(exc).__name__}")
    try:
        final = set(db.list_graphs())
        out["leftover_graphs"] = sorted(n for n in created_graphs if n in final)
        leftover_rows = []
        for tid in sorted(created_tenants):
            rows = db.ro_query(REGISTRY_GRAPH, Q_REGISTRY_EXISTS, {"id": tid},
                               op="dogfood.cleanup.verify").result_set or []
            if rows:
                leftover_rows.append(tid)
        out["leftover_rows"] = leftover_rows
        out["graphs_baseline"] = len(baseline_graphs)
        out["graphs_final"] = len(final)
        out["graphs_new_vs_baseline"] = sorted(final - baseline_graphs)
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"final verify: {type(exc).__name__}")
    return out


# --------------------------------------------------------------------------------------
# Runner + report
# --------------------------------------------------------------------------------------
def resolve_outcome(expect: Expectation, result: ScenarioResult) -> str:
    if result.skipped is not None:
        return "SKIP"
    if expect.expect == "pass":
        return "PASS" if result.ok else "FAIL"
    return "STALE" if result.ok else "EXPECTED-FAIL"


def outcome_label(row: Row) -> str:
    if row.outcome == "EXPECTED-FAIL":
        return f"EXPECTED-FAIL({row.expectation.pids})" if row.expectation.pids else "EXPECTED-FAIL"
    if row.outcome == "SKIP":
        return f"SKIP({mask(row.result.skipped or '')})"
    if row.outcome == "STALE":
        return "STALE (flip to pass)"
    return row.outcome


def run_scenarios(ctx: Ctx, ids: list[str]) -> list[Row]:
    rows: list[Row] = []
    for sid in ids:
        expectation = EXPECTATIONS[sid]
        result = ScenarioResult()
        started = time.perf_counter()
        try:
            SCENARIO_FUNCS[sid](ctx, result)
        except SkipScenario as exc:
            result.skipped = str(exc)
        except Exception as exc:  # noqa: BLE001 - a crashed scenario is a FAIL with evidence
            result.checks.append(Check("scenario crashed", False,
                                       f"{type(exc).__name__}: {exc}"[:400]))
        outcome = resolve_outcome(expectation, result)
        row = Row(sid, SCENARIO_TITLES[sid], expectation, result, outcome)
        rows.append(row)
        elapsed = round((time.perf_counter() - started) * 1000.0)
        print(f"{sid:<5} {outcome_label(row):<24} {mask(result.summary)}  [{elapsed} ms]",
              flush=True)
    return rows


def summary_counts(rows: list[Row], strict: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.outcome] = counts.get(row.outcome, 0) + 1
    counts["failing"] = sum(
        1 for row in rows
        if row.outcome in ("FAIL", "STALE")
        or (strict and row.outcome == "EXPECTED-FAIL")
    )
    return counts


def build_report(
    rows: list[Row],
    ctx: Ctx,
    meta: dict[str, Any],
    counts: dict[str, int],
    strict: bool,
    started: str,
    finished: str,
    fatal: str | None,
) -> str:
    stale = [row.scenario for row in rows if row.outcome == "STALE"]
    lines: list[str] = []
    add = lines.append
    add(f"# Dogfood report — {finished} (UTC {started})")
    add("")
    add(f"- mode: **{ctx.mode}** | base: `{ctx.base}` | strict: {strict}")
    add(f"- git: `{meta.get('head')}` | working tree: {frag(meta.get('git_status'), 300)}")
    add(f"- python: `{meta.get('python')}` | DB: `{meta.get('db')}`")
    if ctx.log_path is not None:
        add(f"- server log: `{ctx.log_path}`")
    add(f"- graph set: baseline {meta.get('graphs_baseline')} -> final {meta.get('graphs_final')}"
        f" | new vs baseline: {meta.get('graphs_new_vs_baseline')}")
    if fatal:
        add(f"- **FATAL: {fatal}**")
    add("")
    add("## Summary")
    add("")
    add(f"{counts.get('PASS', 0)} PASS | {counts.get('FAIL', 0)} FAIL | "
        f"{counts.get('EXPECTED-FAIL', 0)} EXPECTED-FAIL | {counts.get('STALE', 0)} STALE | "
        f"{counts.get('SKIP', 0)} SKIP | failing total: {counts.get('failing', 0)}")
    add("")
    add("| id | scenario | expected today | outcome | P-ids | evidence |")
    add("|----|----------|----------------|---------|-------|----------|")
    for row in rows:
        add(f"| {row.scenario} | {row.title} | {row.expectation.label} | "
            f"{frag(outcome_label(row), 120)} | {row.expectation.pids or '-'} | "
            f"{frag(mask(row.result.summary), 220)} |")
    add("")
    if stale:
        add(f"**STALE EXPECTATIONS (flip these): {', '.join(stale)}**")
        add("")
    add("## Scenario detail")
    add("")
    for row in rows:
        add(f"### {row.scenario} — {row.title}")
        add("")
        add(f"- outcome: `{outcome_label(row)}` | expectation: `{row.expectation.label}` | "
            f"P-ids: {row.expectation.pids or '-'}")
        add(f"- why this row exists: {row.expectation.note}")
        if row.result.skipped is not None:
            add(f"- skipped because: {mask(row.result.skipped)}")
        for check in row.result.checks:
            add(f"- [{'ok' if check.ok else 'BAD'}] {check.name} — {mask(check.evidence)}")
        for note in row.result.info:
            add(f"- info: {mask(note)}")
        add("")
    add("## Cleanup")
    add("")
    cleanup = ctx.state.get("cleanup", {}) if hasattr(ctx, "state") else {}
    for key in ("graphs_deleted", "graphs_absent", "rows_deleted", "rows_leftover",
                "leftover_graphs", "leftover_rows", "errors", "skipped"):
        value = cleanup.get(key)
        if value:
            add(f"- {key}: {frag(value, 400)}")
    add(f"- created tenants: {frag(sorted(ctx.created_tenants), 400)}")
    add(f"- created graphs: {frag(sorted(ctx.created_graphs), 400)}")
    add(f"- tenant creation paths: {frag(ctx.state.get('tenant_paths', {}), 300)}")
    add("")
    add("## Notes and limits")
    add("")
    add("- S01: the registry graph name is not configurable (TenantRegistry hardcodes "
        "`graph_name('registry')` -> `ped:registry`; `pedigree.config.REGISTRY_GRAPH` is only used "
        "by the unused `ensure_registry_schema`). The row reports whether it ran or skipped.")
    add("- S14 sends `X-Admin-Token`; metrics authentication is required, and P-022 tracks instrumentation.")
    add("- S08 requires the product's typed invalid_argument envelope; raw Pydantic input echoes fail.")
    add("- S11's forged Content-Length is rejected by h11 at the protocol level "
        "(\"Invalid HTTP request received.\", 400) before BodySizeMiddleware (same status either way).")
    add("- Cleanup only touches ids this run created; it never enumerates or deletes other tenants.")
    add("- Attach mode assumes the harness process and the target server share the same FalkorDB.")
    add("")
    add("## Machine-readable outcomes")
    add("")
    payload = [{"id": row.scenario, "expected": row.expectation.label, "outcome": row.outcome,
                "pids": row.expectation.pids,
                "checks": [{"name": c.name, "ok": c.ok, "evidence": mask(c.evidence)}
                           for c in row.result.checks],
                "skipped": mask(row.result.skipped) if row.result.skipped else None}
               for row in rows]
    add("```json")
    add(json.dumps(payload, indent=1))
    add("```")
    add("")
    return mask("\n".join(lines), ctx.secrets)


def print_summary(rows: list[Row], counts: dict[str, int], stale: list[str], report_path: Path,
                  strict: bool) -> None:
    print("")
    width = max((len(r.scenario) for r in rows), default=4) + 2
    print("=" * 100)
    print(f"{'ID':<{width}}{'OUTCOME':<24}{'EXPECTED':<26}EVIDENCE")
    print("-" * 100)
    for row in rows:
        print(f"{row.scenario:<{width}}{outcome_label(row):<24}{row.expectation.label:<26}"
              f"{frag(mask(row.result.summary), 90)}")
    print("=" * 100)
    print(f"PASS={counts.get('PASS', 0)} FAIL={counts.get('FAIL', 0)} "
          f"EXPECTED-FAIL={counts.get('EXPECTED-FAIL', 0)} STALE={counts.get('STALE', 0)} "
          f"SKIP={counts.get('SKIP', 0)} strict={strict}")
    if stale:
        print(f"STALE EXPECTATIONS (flip these): {', '.join(stale)}")
    print(f"report: {report_path}")
    print(f"exit: {'0 (all scenarios match expectations)' if not counts.get('failing') else '1'}")


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dogfood.py",
        description="Brutal heavy-user dogfood harness for Pedigree (spawn or attach mode).",
    )
    parser.add_argument("--base-url", default=None,
                        help="attach to an already-running server (default: spawn one)")
    parser.add_argument("--admin-token", default=os.environ.get("PEDIGREE_ADMIN_TOKEN") or None,
                        help="admin token for attach mode (default: $PEDIGREE_ADMIN_TOKEN)")
    parser.add_argument("--strict", action="store_true",
                        help="expected-failures count as failures (exit 1)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stamp, local = parse_ts()
    report_path = SCRATCH_DIR / f"{stamp}.md"

    db: Db | None = None
    baseline_graphs: set[str] = set()
    try:
        db = Db(Settings())
        if not db.ping():
            db = None
    except Exception:  # noqa: BLE001 - the harness reports this instead of crashing
        db = None
    if db is not None:
        with contextlib.suppress(Exception):
            baseline_graphs = set(db.list_graphs())

    proc: subprocess.Popen | None = None
    log_path = SCRATCH_DIR / f"{stamp}-server.log"
    mode = "spawn"
    if args.base_url:
        mode = "attach"
        base = args.base_url.rstrip("/")
        admin_token = args.admin_token
    else:
        mode = "spawn"
        port = pick_port()
        base = f"http://127.0.0.1:{port}"
        admin_token = "ped_admin_" + secrets.token_urlsafe(24)
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("PEDIGREE_", "FALKOR_"))}
        env.update({"PEDIGREE_ADMIN_TOKEN": admin_token, "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8"})
        log_handle = log_path.open("w", encoding="utf-8")
        cmd = [sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app", "--factory",
               "--host", "127.0.0.1", "--port", str(port)]
        try:
            proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT,
                                    cwd=str(ROOT), env=env)
            wait_ready(base, proc, log_path)
        except Exception as exc:  # noqa: BLE001
            stop_process(proc)
            log_handle.close()
            print(f"FATAL: could not start the server: {type(exc).__name__}: {exc}")
            meta = {"head": git_state()[0], "git_status": git_state()[1], "python": sys.executable,
                    "db": "n/a", "graphs_baseline": len(baseline_graphs)}
            report_path.write_text(
                build_report([], Ctx(base, httpx.Client(), None, db, mode, log_path), meta,
                             {"failing": 1}, args.strict, started, local,
                             f"could not start the server: {exc}"),
                encoding="utf-8")
            print(f"report: {report_path}")
            return 1

    client = httpx.Client(base_url=base, timeout=30.0, follow_redirects=False)
    ctx = Ctx(base, client, admin_token, db, mode, log_path if args.base_url is None else None)
    fatal: str | None = None
    rows: list[Row] = []
    try:
        rows = run_scenarios(ctx, RUN_ORDER)
    except Exception as exc:  # noqa: BLE001 - fatal: report it, never crash silently
        fatal = f"{type(exc).__name__}: {exc}"
        print(f"FATAL during scenarios: {fatal}")
    finally:
        stop_process(proc)
        cleanup = do_cleanup(db, ctx.created_graphs, ctx.created_tenants, baseline_graphs)
        ctx.state["cleanup"] = cleanup
        if db is not None and "skipped" not in cleanup:
            clean_row_result = ScenarioResult()
            with contextlib.suppress(Exception):
                SCENARIO_FUNCS["CLEAN"](ctx, clean_row_result)
            rows.append(Row("CLEAN", SCENARIO_TITLES["CLEAN"], EXPECTATIONS["CLEAN"],
                            clean_row_result, resolve_outcome(EXPECTATIONS["CLEAN"], clean_row_result)))
        client.close()

    counts = summary_counts(rows, args.strict)
    if fatal:
        counts["failing"] = counts.get("failing", 0) + 1
    stale = [row.scenario for row in rows if row.outcome == "STALE"]
    head, git_status = git_state()
    db_desc = "unreachable" if db is None else f"{Settings().falkor_host}:{Settings().falkor_port}"
    graphs_final = cleanup.get("graphs_final", len(baseline_graphs))
    meta = {
        "head": head,
        "git_status": git_status,
        "python": f"{sys.version.split()[0]} @ {sys.executable}",
        "db": db_desc,
        "graphs_baseline": len(baseline_graphs),
        "graphs_final": graphs_final,
        "graphs_new_vs_baseline": cleanup.get("graphs_new_vs_baseline", []),
    }
    report_path.write_text(
        build_report(rows, ctx, meta, counts, args.strict, started, local, fatal), encoding="utf-8")
    print_summary(rows, counts, stale, report_path, args.strict)
    return 1 if counts.get("failing") else 0


if __name__ == "__main__":
    raise SystemExit(main())
