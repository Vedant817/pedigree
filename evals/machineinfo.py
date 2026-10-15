"""machineinfo - recorded in every results file (docs/03 rule zero). Never invents a value."""
from __future__ import annotations

import os
import platform
import subprocess
import sys


def _ram_bytes():
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # noqa: S606
            return int(stat.ullTotalPhys)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:  # noqa: BLE001 - best effort only
        return None


def _commit_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def falkor_version() -> str:
    try:
        from pedigree.db.client import Db

        return str(Db().module_version())
    except Exception:  # noqa: BLE001 - the DB may be down for pure-semantics runs
        return "unavailable"


def collect() -> dict:
    ram = _ram_bytes()
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(ram / 1024 ** 3, 1) if ram else "unknown",
        "python": platform.python_version(),
        "falkor_module_version": falkor_version(),
        "commit_sha": _commit_sha(),
    }


def csv_header_lines(info: dict, extra: dict | None = None) -> list[str]:
    lines = [f"# {k}={v}" for k, v in {**info, **(extra or {})}.items()]
    lines.append("# keys=k = key")
    return lines
