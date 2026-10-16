"""Regression tests for scripts/secret_scan.py (QA finding 2026-10-15: --history crashed
on Windows because subprocess output was decoded with the cp1252 locale; history also
contains bytes that are not valid cp1252)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import secret_scan  # noqa: E402

# A key-shaped value that deliberately avoids the placeholder filter (no example/fake/test...).
# Assembled from fragments so the AWS-key shape never appears verbatim in source. # secret-scan-allow
_PLANTED_AWS_KEY_PARTS = (b"AKIA", b"ZZ7Q2WPLMN4XTUVB")
_PLANTED_AWS_KEY = b"".join(_PLANTED_AWS_KEY_PARTS)
PLANTED_KEY = b"aws_access_key_id = " + _PLANTED_AWS_KEY + b"\n"
# Bytes that are neither valid UTF-8 nor valid cp1252 (0x8f, 0x90) as QA observed at
# history offset 421527; must not crash the scanner.
NON_UTF8_BYTES = b"graph \x8f\x90 module output \x81\x8d\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    return repo


def test_history_scan_survives_non_utf8_bytes(tiny_repo: Path):
    (tiny_repo / "bench.txt").write_bytes(NON_UTF8_BYTES)
    _git(tiny_repo, "add", "-A")
    _git(tiny_repo, "commit", "-q", "-m", "bench output with odd bytes")

    findings = secret_scan.scan_history(tiny_repo)  # must not raise
    assert isinstance(findings, int)


def test_history_scan_finds_a_planted_key(tiny_repo: Path):
    (tiny_repo / "leak.py").write_bytes(b'key = b"' + PLANTED_KEY.strip().split(b"= ")[1] + b'"\n')
    _git(tiny_repo, "add", "-A")
    _git(tiny_repo, "commit", "-q", "-m", "oops")

    assert secret_scan.scan_history(tiny_repo) >= 1


def test_worktree_scan_finds_a_planted_key(tiny_repo: Path):
    (tiny_repo / "leak.py").write_bytes(PLANTED_KEY)
    _git(tiny_repo, "add", "-A")

    assert secret_scan.scan_worktree(tiny_repo) >= 1


def test_cli_history_mode_exits_clean_on_non_utf8_history(tiny_repo: Path):
    (tiny_repo / "bench.txt").write_bytes(NON_UTF8_BYTES)
    _git(tiny_repo, "add", "-A")
    _git(tiny_repo, "commit", "-q", "-m", "odd bytes")

    assert secret_scan.main(["--root", str(tiny_repo), "--history"]) == 0


def test_cli_history_mode_exits_nonzero_on_planted_key(tiny_repo: Path):
    (tiny_repo / "leak.py").write_bytes(PLANTED_KEY)
    _git(tiny_repo, "add", "-A")
    _git(tiny_repo, "commit", "-q", "-m", "oops")

    assert secret_scan.main(["--root", str(tiny_repo), "--history"]) == 1


@pytest.mark.parametrize("role", ["a", "o"])
def test_role_bearer_detected_outside_assignment(role):
    import secrets

    value = "ped_" + role + "_tenant_" + secrets.token_urlsafe(32)
    findings = secret_scan.scan_text("Authorization: Bearer " + value)
    assert any(name == "pedigree_bearer" for _, name, _ in findings)
