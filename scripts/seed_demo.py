#!/usr/bin/env python3
"""Seed authored synthetic S1/S8 fixtures; never print a tenant credential."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pedigree.api.registry import TenantRegistry
from pedigree.config import validate_tenant
from pedigree.db.client import Db
from pedigree.demo import seed_scenarios
from pedigree.errors import NotFoundInGraph


def ensure_demo_tenant(registry, tenant: str, credentials_dir: Path) -> Path | None:
    validate_tenant(tenant)
    try:
        record = registry.get_record(tenant)
    except NotFoundInGraph:
        record = None
    file = credentials_dir / f"demo-{tenant}.json"
    if record is not None:
        if record.status != "active":
            raise ValueError("demo tenant is revoked; choose a new dedicated demo tenant")
        return file if file.exists() else None
    credentials_dir.mkdir(parents=True, exist_ok=True)
    # Reserve the local destination before issuing a credential. Never overwrite.
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            credential = registry.create_tenant(tenant)
            json.dump({"tenant": tenant, "token": credential.token}, stream)
            stream.write("\n")
    except Exception:
        file.unlink(missing_ok=True)
        raise
    return file


def main() -> int:
    try:
        tenant = validate_tenant(os.environ.get("PEDIGREE_DEMO_TENANT", "demo"))
        db = Db()
        registry = TenantRegistry(db)
        scratch = Path(__file__).resolve().parents[1] / "scratch"
        credential_file = ensure_demo_tenant(registry, tenant, scratch)
        result = seed_scenarios(db, tenant)
        print("[seed] " + json.dumps(result, sort_keys=True))
        if credential_file:
            print(f"[seed] local credential file: {credential_file} (keep private; never commit)")
        else:
            print("[seed] existing tenant credential retained; use the previously issued token in the UI")
        return 0
    except Exception:
        print("[seed] failed; check DB configuration, dedicated tenant, and local credential file", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
