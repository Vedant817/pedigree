"""Pedigree command line: cross-platform DB lifecycle, service, seeding (ADR-003).

`pedigree db start` prefers Docker (pinned image falkordb/falkordb:v4.22.1 with the
mandatory module args) and falls back to the Linux no-Docker path
(scripts/start-falkordb.sh: falkordblite redis-server + pinned .so).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from .config import Settings, get_settings

IMAGE = "falkordb/falkordb:v4.22.1"
CONTAINER = "pedigree-db"
VOLUME = "pedigree-dbdata"
FALKOR_ARGS = "TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824"
REDIS_ARGS = "--appendonly yes --save 900 1"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return _run(["docker", "info"], timeout=25).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _container_state(name: str = CONTAINER) -> str:
    r = _run(["docker", "inspect", "-f", "{{.State.Status}}", name])
    return r.stdout.strip() if r.returncode == 0 else "missing"


def _wait_ping(settings: Settings, timeout: float = 60.0) -> bool:
    from .db.client import Db

    deadline = time.time() + timeout
    db = Db(settings)
    while time.time() < deadline:
        if db.ping():
            return True
        db.reset()
        time.sleep(0.5)
    return False


def db_start(settings: Settings) -> int:
    mode = settings.pedigree_db_mode
    if mode == "auto":
        mode = "docker" if _docker_ok() else "so"
    port = settings.falkor_port

    if mode == "docker":
        if not _docker_ok():
            print("[db] docker CLI present but the daemon is not reachable.", file=sys.stderr)
            return 1
        if _container_state() == "running":
            print(f"[db] container {CONTAINER} already running")
        else:
            if _container_state() != "missing":
                _run(["docker", "rm", "-f", CONTAINER])
            if _run(["docker", "image", "inspect", IMAGE]).returncode != 0:
                print(f"[db] pulling {IMAGE} (pinned; never `latest`) ...")
                if subprocess.run(["docker", "pull", IMAGE]).returncode != 0:
                    return 1
            cmd = [
                "docker", "run", "-d", "--name", CONTAINER,
                "-p", f"127.0.0.1:{port}:6379",
                "-v", f"{VOLUME}:/var/lib/falkordb/data",
                "-e", "BROWSER=0",
                "-e", f"REDIS_ARGS={REDIS_ARGS}",
                "-e", f"FALKORDB_ARGS={FALKOR_ARGS}",
                IMAGE,
            ]
            r = _run(cmd)
            if r.returncode != 0:
                print(f"[db] docker run failed: {r.stderr.strip()[:400]}", file=sys.stderr)
                return 1
            print(f"[db] started {IMAGE} as {CONTAINER} on 127.0.0.1:{port}")
    elif mode == "so":
        env = os.environ.copy()
        env.setdefault("PORT", str(port))
        env.setdefault("FALKOR_ARGS", FALKOR_ARGS)
        print("[db] starting via scripts/start-falkordb.sh (no-Docker Linux path)")
        subprocess.Popen(["bash", "scripts/start-falkordb.sh"], env=env)
    else:
        print(f"[db] unknown PEDIGREE_DB_MODE={mode!r}", file=sys.stderr)
        return 1

    if not _wait_ping(settings):
        print("[db] server did not become reachable in time", file=sys.stderr)
        return 1
    return db_status(settings)


def db_stop(settings: Settings) -> int:
    if _docker_ok() and _container_state() != "missing":
        _run(["docker", "rm", "-f", CONTAINER])
        print(f"[db] stopped container {CONTAINER}")
        return 0
    script = os.path.join("scripts", "stop-falkordb.sh")
    if os.path.exists(script):
        subprocess.run(["bash", script], check=False)
        return 0
    print("[db] nothing to stop (no container, no script)")
    return 0


def db_status(settings: Settings) -> int:
    from .db.client import Db

    db = Db(settings)
    if not db.ping():
        print(f"[db] NOT reachable at {settings.falkor_host}:{settings.falkor_port}")
        return 1
    try:
        ver = db.module_version()
    except Exception:  # noqa: BLE001
        ver = None
    graphs = []
    try:
        graphs = db.list_graphs()
    except Exception:  # noqa: BLE001
        pass
    expected = 42201
    flag = "OK" if ver == expected else f"WARNING: expected {expected}"
    print(
        f"[db] reachable at {settings.falkor_host}:{settings.falkor_port} | "
        f"graph module ver {ver} ({flag}) | graphs: {len(graphs)}"
    )
    return 0 if ver == expected else 1


def admin_create_tenant(settings: Settings, tenant_id: str, node_cap: int | None) -> int:
    """First-run bootstrap: deliver both tenant role credentials once."""
    from .api.registry import TenantRegistry
    from .config import admin_token_problem
    from .db.client import Db
    from .errors import PedigreeError

    problem = admin_token_problem(settings)
    if problem is not None:
        print(f"[admin] refusing: {problem}. Provide a strong PEDIGREE_ADMIN_TOKEN "
              "(or PEDIGREE_ENV=dev for local work).", file=sys.stderr)
        return 2
    db = Db(settings)
    registry = TenantRegistry(db, settings)
    try:
        cred = registry.create_tenant(tenant_id, node_cap)
    except PedigreeError as exc:
        print(f"[admin] {exc.code}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"tenant": cred.tenant_id, "token": cred.token,
                      "agent_token": cred.agent_token, "operator_token": cred.operator_token}))
    return 0


def admin_issue_operator(settings: Settings, tenant_id: str, rotate: bool = False) -> int:
    """Explicitly issue or rotate only the operator credential of an existing tenant."""
    from .api.registry import TenantRegistry
    from .config import admin_token_problem
    from .db.client import Db
    from .errors import PedigreeError

    problem = admin_token_problem(settings)
    if problem is not None:
        print(f"[admin] refusing: {problem}. Provide a strong PEDIGREE_ADMIN_TOKEN "
              "(or PEDIGREE_ENV=dev for local work).", file=sys.stderr)
        return 2
    registry = TenantRegistry(Db(settings), settings)
    try:
        token = registry.issue_operator(tenant_id, rotate=rotate)
    except PedigreeError as exc:
        print(f"[admin] {exc.code}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"tenant": tenant_id, "operator_token": token}))
    return 0


def resume_revocations(settings: Settings, tenant: str | None) -> int:
    """P-011 (A1): finish crashed revocations for every registered tenant or one tenant."""
    from .api.registry import TenantRegistry
    from .config import graph_name
    from .db.client import Db
    from .engine.revoke import resume_incomplete
    from .errors import PedigreeError

    db = Db(settings)
    registry = TenantRegistry(db, settings)
    if tenant is not None:
        targets = [tenant]
    else:
        targets = [r.tenant_id for r in registry.list_tenants()]

    finished_total = 0
    for tid in targets:
        gname = graph_name(tid)
        try:
            done = resume_incomplete(db, gname)
        except PedigreeError as exc:
            print(f"[resume] {tid}: failed ({exc.code}): {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - never abort the whole scan for one tenant
            print(f"[resume] {tid}: failed: {exc}", file=sys.stderr)
            return 1
        finished_total += len(done)
        if done:
            print(f"[resume] {tid}: finished {len(done)} revocation(s)")
    print(f"[resume] finished {finished_total} revocation(s) in total")
    return 0


def reconcile_stragglers(settings: Settings, tenant: str | None) -> int:
    """P-024 (B3): repair nodes stranded `quarantined` with no running Revocation."""
    from .api.registry import TenantRegistry
    from .config import graph_name
    from .db.client import Db
    from .engine.revoke import reconcile

    db = Db(settings)
    registry = TenantRegistry(db, settings)
    targets = [tenant] if tenant is not None else [r.tenant_id for r in registry.list_tenants()]
    total = 0
    for tid in targets:
        gname = graph_name(tid)
        try:
            out = reconcile(db, gname)
        except Exception as exc:  # noqa: BLE001
            print(f"[reconcile] {tid}: failed: {exc}", file=sys.stderr)
            return 1
        total += out.get("reconciled", 0)
        if out.get("reconciled"):
            print(f"[reconcile] {tid}: repaired {out.get('reconciled')} node(s)")
    print(f"[reconcile] repaired {total} node(s) in total")
    return 0


def serve(settings: Settings, host: str, port: int) -> int:
    import uvicorn

    uvicorn.run("pedigree.api.app:create_app", factory=True, host=host, port=port,
                log_level="info", proxy_headers=False)
    return 0


def checkpoint_command(settings: Settings, args) -> int:
    """Deployment-local maintenance; credentials stay in the environment."""
    from .api.registry import TenantRegistry
    from .config import KNOWN_DEFAULT_ADMIN_TOKENS, validate_tenant
    from .db.client import Db
    from .engine.checkpoint import Checkpoints
    from .errors import Forbidden, InvalidArgument, PedigreeError

    try:
        token = settings.pedigree_admin_token.strip()
        if not token or token.lower() in KNOWN_DEFAULT_ADMIN_TOKENS:
            raise Forbidden("deployment administrator credential required")
        if getattr(args, "rollback", False) and args.action != "recover":
            raise InvalidArgument("--rollback requires the recover action")
        if args.action not in {"list", "status", "mutex-status"} and not args.writers_stopped:
            raise InvalidArgument("stop every API/MCP/direct writer, then pass --writers-stopped")
        validate_tenant(args.tenant)
        db = Db(settings)
        TenantRegistry(db, settings).get_record(args.tenant)
        manager = Checkpoints(db, args.tenant)
        if args.action == "list":
            result = {"checkpoints": manager.list()}
        elif args.action == "status":
            result = {"pending": manager.pending()}
        elif args.action == "mutex-status":
            result = manager.mutex_status()
        elif args.action == "release-mutex":
            result = manager.release_mutex(confirmed=args.confirm_mutex_release)
        elif args.action == "recover":
            result = manager.recover(rollback=args.rollback)
        else:
            if not args.name:
                raise InvalidArgument("--name is required")
            result = getattr(manager, args.action)(args.name)
        print(json.dumps(result))
        return 0
    except PedigreeError as exc:
        print(json.dumps(exc.to_dict()), file=sys.stderr)
        return 1
    except Exception:
        print('[checkpoint] unavailable; keep writers stopped and inspect checkpoint status', file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="pedigree", description="Pedigree service and tooling")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_db = sub.add_parser("db", help="FalkorDB lifecycle")
    p_db.add_argument("action", choices=["start", "stop", "status"])

    p_serve = sub.add_parser("serve", help="run the API + MCP + UI service")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    p_mcp = sub.add_parser("mcp", help="run the MCP server")
    p_mcp.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    p_mcp.add_argument("--host", default="127.0.0.1")
    p_mcp.add_argument("--port", type=int, default=8011)

    p_admin = sub.add_parser("admin", help="admin tooling (first-run bootstrap, no HTTP)")
    p_admin_sub = p_admin.add_subparsers(dest="admin_cmd", required=True)
    p_create = p_admin_sub.add_parser("create-tenant",
                                      help="create a tenant and print its agent/operator credentials once")
    p_create.add_argument("--id", required=True)
    p_create.add_argument("--cap", type=int, default=None)
    p_operator = p_admin_sub.add_parser("issue-operator",
                                      help="issue an existing tenant's operator credential once")
    p_operator.add_argument("--id", required=True)
    p_operator.add_argument("--rotate", action="store_true",
                            help="replace an already issued operator credential (invalidates the old one)")

    p_resume = sub.add_parser("resume", help="finish crashed (`running`) revocations and exit")
    p_resume.add_argument("--tenant", default=None, help="limit to one tenant (default: all)")

    p_reconcile = sub.add_parser("reconcile", help="repair stragglers (quarantined without running)")
    p_reconcile.add_argument("--tenant", default=None, help="limit to one tenant (default: all)")

    p_checkpoint = sub.add_parser("checkpoint", help="offline administrator snapshots; stop all writers first")
    p_checkpoint.add_argument("action", choices=["create", "list", "drop", "restore", "recover", "status",
                                                  "mutex-status", "release-mutex"])
    p_checkpoint.add_argument("--tenant", required=True)
    p_checkpoint.add_argument("--name")
    p_checkpoint.add_argument("--writers-stopped", action="store_true")
    p_checkpoint.add_argument("--confirm-mutex-release", action="store_true",
                              help="acknowledge all database work is quiescent before removing a stranded mutex")
    p_checkpoint.add_argument("--rollback", action="store_true", help="recover the pre-restore graph")

    sub.add_parser("seed", help="seed the demo tenant (synthetic scenarios)")
    sub.add_parser("version", help="print version")

    args = parser.parse_args(argv)

    if args.cmd == "db":
        return {"start": db_start, "stop": db_stop, "status": db_status}[args.action](settings)
    if args.cmd == "serve":
        return serve(settings, args.host, args.port)
    if args.cmd == "mcp":
        from .mcp_server import build_mcp

        srv = build_mcp(
            settings=settings,
            default_tenant_id=os.getenv("PEDIGREE_MCP_TENANT"),
            default_tenant_token=os.getenv("PEDIGREE_MCP_TOKEN"),
        )
        return srv.run(args.transport, args.host, args.port) or 0
    if args.cmd == "admin":
        if args.admin_cmd == "issue-operator":
            return admin_issue_operator(settings, args.id, args.rotate)
        return admin_create_tenant(settings, args.id, args.cap)
    if args.cmd == "resume":
        return resume_revocations(settings, args.tenant)
    if args.cmd == "reconcile":
        return reconcile_stragglers(settings, args.tenant)
    if args.cmd == "checkpoint":
        return checkpoint_command(settings, args)
    if args.cmd == "seed":
        from . import __version__  # noqa: F401  (import check)

        script = os.path.join("scripts", "seed_demo.py")
        if not os.path.exists(script):
            print("[seed] scripts/seed_demo.py not implemented yet", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, script], check=False).returncode
    if args.cmd == "version":
        from . import __version__

        print(f"pedigree {__version__}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
