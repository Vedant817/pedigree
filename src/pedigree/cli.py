"""Pedigree command line: cross-platform DB lifecycle, service, seeding (ADR-003).

`pedigree db start` prefers Docker (pinned image falkordb/falkordb:v4.22.1 with the
mandatory module args) and falls back to the Linux no-Docker path
(scripts/start-falkordb.sh: falkordblite redis-server + pinned .so).
"""

from __future__ import annotations

import argparse
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


def serve(settings: Settings, host: str, port: int) -> int:
    import uvicorn

    uvicorn.run("pedigree.api.app:app", host=host, port=port, log_level="info")
    return 0


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
