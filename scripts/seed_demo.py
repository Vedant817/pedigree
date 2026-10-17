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


class SeedError(ValueError):
    """Authored, credential-free seed failure with an actionable message."""


def ensure_demo_tenant(registry, tenant: str, credentials_dir: Path) -> Path | None:
    validate_tenant(tenant)
    try:
        record = registry.get_record(tenant)
    except NotFoundInGraph:
        record = None
    file = credentials_dir / f"demo-{tenant}.json"
    if record is not None:
        if record.status != "active":
            raise SeedError("demo tenant is revoked; choose a new dedicated demo tenant")
        return file if file.exists() else None
    credentials_dir.mkdir(parents=True, exist_ok=True)
    if file.exists():
        # The tenant is gone from the registry, so a credential file for it is stale *only if*
        # it is readable JSON whose token no longer resolves. Anything else is left alone and
        # the O_EXCL create below refuses - a local credential is never silently overwritten.
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict) and registry.resolve(payload.get("token", "")) is None:
            file.unlink()
    # Reserve the local destination before issuing a credential. Never overwrite.
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            credential = registry.create_tenant(tenant)
            json.dump({"tenant": tenant, "token": credential.token,
                       "agent_token": credential.agent_token,
                       "operator_token": credential.operator_token}, stream)
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
        credentials_dir = Path(os.environ.get("PEDIGREE_CREDENTIALS_DIR",
            str(Path(__file__).resolve().parents[1] / "scratch")))
        credential_file = ensure_demo_tenant(registry, tenant, credentials_dir)
        if credential_file is None:
            raise SeedError("existing demo tenant has no local credential file; restore the "
                            "private file or choose a new dedicated PEDIGREE_DEMO_TENANT")
        result = seed_scenarios(db, tenant)
        print("[seed] " + json.dumps(result, sort_keys=True))
        if credential_file:
            print(f"[seed] local credential file: {credential_file} (keep private; never commit)")
        else:
            print("[seed] existing tenant credentials retained; use the previously issued operator "
                  "token in the UI. For a legacy tenant, explicitly run pedigree admin "
                  "issue-operator --id <tenant>.")
        return 0
    except SeedError as exc:
        print(f"[seed] failed: {exc}", file=sys.stderr)
        print("[seed] seeding errors stop startup; nothing was deleted", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - no provider exception text or credentials
        print(f"[seed] failed ({type(exc).__name__})", file=sys.stderr)
        print("[seed] check DB configuration, the dedicated demo tenant and the local credential file",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
