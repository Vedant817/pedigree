#!/usr/bin/env python3
"""Secret scan: fail the build if a credential is about to be committed.

Scans every tracked file (and, with --history, every blob in git history) for the
usual token shapes. Findings print file:line and the pattern name - NEVER the
secret itself (only its length), so terminal output can be pasted into issues.

Allowlist: obvious placeholder values (change-me, example, fake, dummy, your-...)
and lines carrying `secret-scan-allow` are skipped deliberately, per file.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("pedigree_bearer", re.compile(r"\bped_[ao]_[a-z0-9]{3,24}_[A-Za-z0-9_\-]{43}(?![A-Za-z0-9_\-])")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    (
        "assigned_secret",
        re.compile(
            r"""(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['"]([A-Za-z0-9_\-./+]{16,})['"]"""
        ),
    ),
]

PLACEHOLDER_HINTS = ("change", "example", "fake", "dummy", "placeholder", "xxxx", "your-", "abc123")

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".zip", ".so", ".rdb", ".aof", ".lock")

MAX_FILE_BYTES = 2 * 1024 * 1024


def _placeholder(value: str) -> bool:
    low = value.lower()
    return any(h in low for h in PLACEHOLDER_HINTS)


def scan_text(text: str) -> list[tuple[int, str, int]]:
    """Return (line_no, pattern_name, match_len) for every hit."""
    hits: list[tuple[int, str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "secret-scan-allow" in line:
            continue
        for name, rx in PATTERNS:
            for m in rx.finditer(line):
                value = m.group(1) if m.lastindex else m.group(0)
                if _placeholder(value):
                    continue
                hits.append((lineno, name, len(value)))
    return hits


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    files = []
    for raw in out.split(b"\x00"):
        if not raw:
            continue
        p = root / raw.decode("utf-8", "replace")
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        files.append(p)
    return files


def scan_worktree(root: Path) -> int:
    findings = 0
    for p in tracked_files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, name, length in scan_text(text):
            print(f"[secret-scan] {p.relative_to(root)}:{lineno} -> {name} (secret length {length})")
            findings += 1
    return findings


def scan_history(root: Path) -> int:
    """Scan every added line in `git log -p --all`; report commit + pattern only."""
    proc = subprocess.run(
        ["git", "log", "-p", "--all", "--no-color", "--pretty=format:@%h"],
        cwd=root,
        capture_output=True,
        text=True,
        # Windows locale is cp1252, but history contains bytes that are not valid
        # cp1252 (verified: OffsetError on 0x8f) - force utf-8 with replacement.
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or proc.stdout is None:
        print("[secret-scan] git history unavailable (no commits yet?)")
        return 0
    findings = 0
    commit = "?"
    for line in proc.stdout.splitlines():
        if line.startswith("@"):
            commit = line[1:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for _lineno, name, length in scan_text(line[1:]):
            print(f"[secret-scan] history {commit} -> {name} (secret length {length})")
            findings += 1
    return findings

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="scan tracked files for secrets")
    ap.add_argument("--history", action="store_true", help="also scan all git history")
    ap.add_argument("--root", default=None, help="repository root (default: cwd)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path.cwd()
    findings = scan_worktree(root)
    if args.history:
        findings += scan_history(root)
    if findings:
        print(f"[secret-scan] FAIL: {findings} finding(s). Remove the value and rotate it.")
        return 1
    print("[secret-scan] PASS: no credential shapes found in tracked files"
          + (" or git history" if args.history else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
