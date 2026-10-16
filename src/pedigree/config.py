"""Configuration, enums, limits and the tenant -> graph-name choke point.

Tenant ids are `^[a-z0-9]{3,24}$`; graph names are `ped:<tenant>` (delimiter form so ACL
patterns `~ped:abc` cannot match tenant `abcd`, GOTCHAS #17). Every graph name used by the
product is produced by the functions in this module - nothing else may build one.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import InvalidArgument

TENANT_RE = re.compile(r"^[a-z0-9]{3,24}$")
WI_TOKEN_RE = re.compile(r"^[0-9a-f]{8}$")
CK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")

REGISTRY_GRAPH = "pedigree:registry"

# --- vocabulary (docs/01 section 5) -----------------------------------------
NODE_TYPES = ("Source", "Memory", "Action", "Session", "Agent", "Revocation")
STATUS_ALL = ("ok", "quarantined", "tainted", "preserved", "revoked")
STATUS_MEMORY = STATUS_ALL
STATUS_SOURCE = ("ok", "revoked")
STATUS_ACTION = ("ok", "quarantined", "tainted")

SOURCE_KINDS = (
    "user_prompt", "file", "web", "tool_output", "rules_file", "mcp_tool_desc", "human", "other",
)
MEMORY_KINDS = ("fact", "summary", "decision", "preference", "procedure", "rule")
EFFECTS = ("reversible", "irreversible", "unknown")
RISKS = ("low", "medium", "high")
INTEGRITY = ("trusted", "untrusted")

#: Source kinds that are untrusted by default (docs/01 section 6.5).
UNTRUSTED_KINDS = frozenset({"web", "tool_output", "mcp_tool_desc"})

#: Anything that can have DERIVED_FROM parents.
DERIVABLE = ("Memory", "Action")
#: Anything that can be revoked as a root.
REVOCABLE = ("Source", "Memory")

# --- limits (docs/01 section 9) ---------------------------------------------
LIMITS = {
    "body_bytes": 256 * 1024,
    "id_len": 128,
    "text_len": 2000,
    "summary_len": 300,
    "uri_len": 512,
    "title_len": 160,
    "reason_len": 300,
    "relied_on": 64,
    "derived_from": 64,
    "corroborated_by": 16,
    "conf_tags": 8,
    "artifact_str_len": 512,
    "artifacts": 16,
    "depth_max": 12,
    "whatif_roots": 5,
    "audit_limit": 50,
    "events_per_request": 500,
    "chunk": 2000,
}
# Node ids: the pack's regex plus `_` (auto-generated ids are `src_<hex>`, `mem_<hex>`, ...;
# see ADR-004). Artifacts are file paths/URLs/commit shas and may contain spaces and `\`.
ID_RE = re.compile(r"^[A-Za-z0-9._:/@#_-]{1,128}$")
ARTIFACT_RE = re.compile(r"^[^\x00-\x1f]{1,512}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    falkor_host: str = "127.0.0.1"
    falkor_port: int = 6379
    falkor_username: str | None = None
    falkor_password: str | None = None

    pedigree_admin_token: str = ""
    pedigree_env: str = "dev"  # dev|test|local are lenient; anything else refuses empty/default admin tokens
    pedigree_public_docs: bool = False
    pedigree_secret: str = ""
    pedigree_node_cap: int = 200_000
    pedigree_store_text: bool = False
    pedigree_read_window: int = 50
    pedigree_public_url: str = "http://127.0.0.1:8000"
    pedigree_policy_file: str = "policy.yaml"
    pedigree_db_acl: bool = True
    pedigree_db_mode: str = "auto"  # auto|docker|so  (how `pedigree db start` runs FalkorDB)

    llm_provider: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # read/write query timeouts (ms)
    read_timeout_ms: int = 5_000
    write_timeout_ms: int = 15_000

    @model_validator(mode="after")
    def _check_timeouts(self) -> "Settings":  # noqa: UP037
        for name in ("read_timeout_ms", "write_timeout_ms"):
            val = getattr(self, name)
            if val < 1 or val > 60_000:
                raise ValueError(f"{name} must be between 1 and 60000")
        return self


DEV_ENVS = {"dev", "test", "local"}
KNOWN_DEFAULT_ADMIN_TOKENS = {"change-me-admin", "change-me", "changeme"}


def admin_token_problem(settings: Settings) -> str | None:
    """Shared fail-closed guard (P-013): why the admin token is unusable, or None.

    Non-dev environments refuse an empty or known-default token; dev/test/local accept
    anything so a local checkout works without ceremony.
    """
    token = (settings.pedigree_admin_token or "").strip()
    env = (settings.pedigree_env or "dev").strip().lower()
    if env in DEV_ENVS:
        return None
    if not token:
        return "PEDIGREE_ADMIN_TOKEN is empty"
    if token.lower() in KNOWN_DEFAULT_ADMIN_TOKENS:
        return "PEDIGREE_ADMIN_TOKEN is a known-default value; generate a strong token"
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def graph_name(tenant: str) -> str:
    """The single choke point that turns a tenant id into a graph name."""
    if not isinstance(tenant, str) or not TENANT_RE.fullmatch(tenant):
        raise InvalidArgument("invalid tenant id", detail={"tenant": str(tenant)[:64]})
    return f"ped:{tenant}"


def validate_tenant(tenant: str) -> str:
    """Assert a tenant id at an engine boundary (F-05 will derive it from the token only)."""
    if not isinstance(tenant, str) or not TENANT_RE.fullmatch(tenant):
        raise InvalidArgument("invalid tenant id", detail={"tenant": str(tenant)[:64]})
    return tenant


def whatif_graph_name(tenant: str, token: str) -> str:
    base = graph_name(tenant)
    if not isinstance(token, str) or not WI_TOKEN_RE.fullmatch(token):
        raise InvalidArgument("invalid what-if token", detail={"token": str(token)[:32]})
    return f"{base}:wi:{token}"


def checkpoint_graph_name(tenant: str, name: str) -> str:
    base = graph_name(tenant)
    if not isinstance(name, str) or not CK_NAME_RE.fullmatch(name):
        raise InvalidArgument("invalid checkpoint name", detail={"name": str(name)[:32]})
    return f"{base}:ck:{name}"


def validate_id(value: str | None) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise InvalidArgument("invalid id", detail={"id": (str(value) if value else "")[:64]})
    return value


def validate_artifact(value: str | None) -> str:
    if not isinstance(value, str) or not ARTIFACT_RE.fullmatch(value):
        raise InvalidArgument("invalid artifact string", detail={"artifact": (str(value) if value else "")[:64]})
    return value


def default_integrity(kind: str) -> str:
    return "untrusted" if kind in UNTRUSTED_KINDS else "trusted"
