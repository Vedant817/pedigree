"""Owned, bounded local runtime. Never stop a process discovered by port or name."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_SHA256 = '84ff87446c8c2b4506f32baf675e607512f2a16f1b49e40fab26f505209a0335'
MODULE_URL = 'https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.1/falkordb-x64.so'
LIMITS = {'TIMEOUT_MAX': 60000, 'TIMEOUT_DEFAULT': 20000, 'QUERY_MEM_CAPACITY': 1073741824}


def free_port(port: int) -> None:
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'port {port} is occupied; refusing to reuse or stop its listener') from None


def fetch() -> Path:
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise RuntimeError('the verified pinned module path requires Linux x86_64; native macOS is unverified')
    dest = ROOT / 'bin/falkordb-4.22.1-x64.so'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        temporary = dest.with_suffix(f'.{os.getpid()}.download')
        try:
            urllib.request.urlretrieve(MODULE_URL, temporary)
            if hashlib.file_digest(temporary.open('rb'), 'sha256').hexdigest() != MODULE_SHA256:
                raise RuntimeError('pinned module digest mismatch')
            temporary.replace(dest)
        finally:
            temporary.unlink(missing_ok=True)
    with dest.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != MODULE_SHA256:
            raise RuntimeError('pinned module digest mismatch; existing file was not changed')
    dest.chmod(0o755)
    print('[runtime] pinned FalkorDB4.22.1 module SHA256 verified')
    return dest


def redis_server() -> Path:
    spec = importlib.util.find_spec('redislite')
    if spec is None or spec.origin is None:
        raise RuntimeError('redislite missing; install locked dev/localdb extras')
    candidate = Path(spec.origin).parent / 'bin/redis-server'
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError('installed redislite redis-server is unavailable')
    return candidate


def config_value(db, name: str) -> int:
    """Read one mandatory GRAPH.CONFIG value; accept flat and nested reply shapes."""
    result = db.client.connection.execute_command('GRAPH.CONFIG', 'GET', name)
    pair = result[0] if result and isinstance(result[0], (list, tuple)) else result
    if not pair or len(pair) < 2 or str(pair[0]) != name:
        raise RuntimeError(f'database required limit {name} is unavailable')
    try:
        return int(pair[1])
    except (TypeError, ValueError):
        raise RuntimeError(f'database required limit {name} is not an integer') from None


def wait_db(timeout: float = 30, process=None) -> None:
    from pedigree.config import Settings
    from pedigree.db.client import Db
    db = Db(Settings(_env_file=None))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError('owned database process exited before readiness')
        if db.ping():
            if db.module_version() != 42201:
                raise RuntimeError('database must run FalkorDB module42201')
            for name, expected in LIMITS.items():
                if config_value(db, name) != expected:
                    raise RuntimeError(f'database required limit {name} differs')
            print('[runtime] database module42201 and mandatory limits verified')
            return
        time.sleep(.25)
    raise RuntimeError('database readiness deadline exceeded')


@contextmanager
def owned_data(path: Path):
    import fcntl
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path / '.runtime.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('data directory belongs to another active runtime') from None
        # Retain the lock through exec of the foreground Redis process.
        os.set_inheritable(stream.fileno(), True)
        yield


def module_dependencies(module: Path) -> list[str]:
    """Missing shared libraries for the pinned module (empty when ldd is unavailable)."""
    if shutil.which('ldd') is None:
        return []
    result = subprocess.run(['ldd', str(module)], capture_output=True, text=True, check=False)
    return sorted({line.split()[0] for line in (result.stdout or '').splitlines() if 'not found' in line})


def run_db() -> None:
    if platform.system() != 'Linux':
        raise RuntimeError('no-Docker runtime is verified only on Linux; Windows uses Docker')
    port = int(os.environ.get('FALKOR_PORT', os.environ.get('PORT', '6379')))
    free_port(port)
    module = fetch()
    missing = module_dependencies(module)
    if missing:
        raise RuntimeError(f'pinned module needs missing system libraries: {", ".join(missing)}; '
                           'on Debian/Ubuntu install libgomp1 (Fedora: libgomp)')
    server = redis_server()
    data = Path(os.environ.get('DATA_DIR', str(ROOT / 'data/local'))).resolve()
    with owned_data(data):
        args = [str(server), '--bind', '127.0.0.1', '--port', str(port), '--dir', str(data),
                '--appendonly', 'yes', '--save', '900', '1', '--loadmodule', str(module)]
        for name, value in LIMITS.items():
            args.extend([name, str(value)])
        os.execv(str(server), args)


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def quickstart() -> int:
    if platform.system() != 'Linux':
        raise RuntimeError('use the separate Windows Docker setup; native macOS unverified')
    port = int(os.environ.get('PEDIGREE_PORT', '8000'))
    db_port = int(os.environ.get('FALKOR_PORT', '6379'))
    free_port(port)
    free_port(db_port)
    data = Path(os.environ.get('DATA_DIR', str(ROOT / 'data/local'))).resolve()
    env = {**os.environ, 'FALKOR_HOST': '127.0.0.1', 'FALKOR_PORT': str(db_port),
           'DATA_DIR': str(data), 'PEDIGREE_SEED_DEMO': '1',
           'PEDIGREE_CREDENTIALS_DIR': os.environ.get('PEDIGREE_CREDENTIALS_DIR', str(data / 'credentials'))}
    # Settings must match the owned child, never an unrelated .env database.
    os.environ.update({key: env[key] for key in ('FALKOR_HOST', 'FALKOR_PORT')})
    processes = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        db = subprocess.Popen([sys.executable, __file__, 'db'], env=env, start_new_session=True)
        processes.append(db)
        wait_db(process=db)
        subprocess.run([sys.executable, str(ROOT / 'scripts/seed_demo.py')], env=env, check=True)
        api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'pedigree.api.app:create_app',
            '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-proxy-headers'],
            env=env, start_new_session=True)
        processes.append(api)
        print(f'[runtime] API http://127.0.0.1:{port}; Ctrl-C stops only this runtime', flush=True)
        while api.poll() is None and db.poll() is None:
            time.sleep(.2)
        return api.returncode if api.returncode is not None else 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            stop_owned(process)


def main() -> int:
    try:
        command = sys.argv[1]
        if command == 'fetch':
            fetch()
        elif command == 'wait-db':
            wait_db()
        elif command == 'db':
            run_db()
        elif command == 'quickstart':
            return quickstart()
        else:
            raise RuntimeError('unknown runtime command')
        return 0
    except Exception as exc:  # noqa: BLE001 - authored messages never contain credentials
        print(f'[runtime] failed ({type(exc).__name__}): {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
