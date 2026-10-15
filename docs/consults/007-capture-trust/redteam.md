# Red-team consult 007 - capture trust: stable Source identity + authority separation

Probes ran against local FalkorDB v4.22.1 in throwaway tenant graphs + registry rows under gitignored `scratch/`, deleted afterwards. Every claim is measured; no token is printed.

## (a) Attacks available today

| # | Hole | Endpoint / tool | Request shape (agent's own tenant token) | Measured effect |
|---|---|---|---|---|
| 1 | identity | `record_source` (engine/MCP) and `POST /v1/events` | 2x `kind="file", uri="docs/rules.md", content_hash=h`; 3x hook `{"type":"source_read","source_kind":"rules_file","uri":"docs/rules.md","content_hash":h,"id":"src_<rand>"}` | ids `src_9203693b`/`src_dd2e9841`, `count(Source{uri})=2`; hook path gives **3 nodes** for one path@sha. `artifact_lookup` matches Memory/Action only, so the next identical read mints yet another |
| 2 | identity | `revoke` + a later identical read | `revoke(root_id=copy#1)`, then Read the same path@sha | copy#1 revoked, **twin stays `ok`**; the new session's read window points at the twin -> revocation never covers future identical reads |
| 3 | identity | any write path | 200 identical reads | **200 Source nodes** = 200 quota units + 200 revocation roots; burns the tenant node cap -> `quota_exceeded` on every later write |
| 4 | authority | `POST /v1/corroborate` | `{"memory_id":"mem","source_id":"src_fake","by":"human"}` | `200 {"ok":true}`; after `revoke(src_rules)` mem = `preserved`; `check_action(git push --force, irreversible/high)` -> **allow**, reason `preserved_lineage` |
| 5 | authority | MCP `pedigree_corroborate` / `POST /v1/sources` | `by="scanner"`; `{"kind":"web","uri":"http://evil.example/payload","integrity":"trusted"}` | `{"ok":true}` (the tool passes `by` straight through, mcp_server.py:128-133); `low_integrity=false`, inherited by any Memory derived from it, so gate rule 3 `untrusted_influence` can never fire -> **allow**, `reasons=[]` |
| 6 | authority | `POST /v1/sources` / `POST /v1/events` | `{"kind":"human","uri":"..."}` with **no** `integrity` field; or `{"type":"source_read","source_kind":"web","integrity":"trusted","id":"src_chosen_by_caller"}` | `low_integrity=false` - `kind` is caller-asserted too and `human|file|rules_file|user_prompt` default trusted (config.py:145-147); the events path stores `['trusted', false]` under a caller-chosen id |
| 7 | authority | `corroborate` (engine) | `by="human"`, then `by="agent"` on the same edge | `Q_CORROBORATE` is `MERGE ... SET r.by`, an overwrite: an injected prompt **deletes a real human attestation** (gate flips allow -> block) and can mint its own |

## (b) Stop or move?

- **Separate human role token** - **moves it.** `authenticate()` resolves one tenant per token and `TenantRecord` has no role (auth.py:48-66, registry.py:31-35): a second bearer string on the same host, in the same `.env`/MCP config the agent reads. "Forge a string in a body" becomes "read a string from a file" - same difficulty class for a solo dev, and it re-opens the moment the token is pasted into the agent's env (how F-11 happened). Additive only, and only failing closed.
- **Structural agents-may-only-downgrade** - **stops 4, 5, 6**: the parameter is not expressible, so there is no call to forge (schema change, not a policy check). **Not 7**: needs write-once edges. Nothing for 1-3.
- **UI-only authority claim (`by='human_ui'`, untrusted)** - **stops nothing**: the in-toto §4.3.1 demoted field, plus a new enum value a later call site may promote. The UI is read-only today (routes/workspace.py), so it also means building a write channel. Keep only as demo honesty.
- **Server-side attestation (hook / CLI / UI session)** - **stops 4-6 in principle** (authority bound to a channel, not a string), but on one host every channel is reachable by the same principal and docs/01 §9 already lists forged hook payloads as residual. It *is* the right home for hole 1's key: derive it from the observed artifact, never from the caller.

## (c) Recommendation - one design: **the engine derives identity and authority; the caller supplies only evidence**

1. **Identity is derived.** Exact-match indexes on `Source(uri)` and `Source(content_hash)`, then the composite unique constraint `Source(uri, content_hash)` - measured expressible on v4.22.1 (both were `REJECTED: missing supporting exact-match index` until the indexes existed; a uri-only constraint rejects a changed page, and neither dedupes uri-less nodes). `record_source` becomes one atomic `MERGE` on that key (measured idempotent: 2 calls -> 1 node, same id); same uri + new hash = a **new version node**, never update-in-place, so the old hash stays revocable. Drop `id` from the agent-facing source schemas.
2. **Authority is derived from the channel.** Delete `by` from `pedigree_corroborate`/`CorroborateRequest` and `integrity` from `pedigree_record_source`/`SourceCreate`/`source_read`; the engine sets `by='agent'` and `integrity=default_integrity(kind)`. Trusted-by-default kinds are assertable only by the hook channel (`runtime in {claude-code, opencode}`); MCP/REST-direct is limited to `web|tool_output|mcp_tool_desc|other`. `CORROBORATED_BY` becomes `ON CREATE SET r.by` (write-once), so downgrade-only is literally true.
3. **Enforce at the route/tool, never by reading `via`:** measured, MCP `pedigree_remember` writes `via='cite'`, identical to a genuine citation.
4. **Human/scanner fails closed:** with no second credential `/v1/corroborate` returns `forbidden` and no `human_ui` value exists. KNOWN_ISSUES 11 closes only in the two-credential configuration and stays a documented limitation in the single-token demo.

Accepted failure modes: a human holding one token cannot corroborate (already ADR-007 rule 2 behaviour); one uri accumulates versions, so `blame` may list several roots; uri-less *and* hash-less sources still need a caller id; a compromised host can still forge a hook payload (docs/01 §9 residual).

## (d) Smallest failing-then-passing test

`tests/security/test_security_F13_authority.py`, `fresh_graph` fixture. **Verified failing today** by running it from `scratch/` (2 failed, today's output quoted inline):

```python
def test_agent_cannot_mint_trusted_support(boundary):
    db, tenant, graph, settings, token, client, headers = boundary
    record_source(db, graph, tenant, id="src_rules", kind="rules_file", uri="CLAUDE.md"); record_source(db, graph, tenant, id="src_fake", kind="file", uri="attacker-minted.md")
    remember(db, graph, tenant, id="mem", text="x", derived_from=["src_rules"], corroborated_by=["src_fake"])
    r = client.post("/v1/corroborate", headers=headers, json={"memory_id": "mem", "source_id": "src_fake", "by": "human"})
    assert r.status_code in (400, 403, 422), r.text    # today: 200 {"ok":true}
    r = client.post("/v1/sources", headers=headers, json={"kind": "web", "uri": "http://e.x/p", "integrity": "trusted"})
    assert r.status_code in (400, 403, 422), r.text    # today: 200, low_integrity=false
    revoke(db, graph, tenant, root_id="src_rules", reason="poisoned")
    v = check_action(db, graph, {"tool": "Bash", "summary": "git push --force", "effect": "irreversible", "risk": "high"}, relied_on=["mem"], policy_path="missing-policy.yaml")
    assert v["decision"] in ("block", "reverify") and any(x["code"] == "tainted_ancestor" for x in v["reasons"])  # today: allow / preserved_lineage
    async def tools(): return {t.name: t for t in await build_mcp(db, settings).server.list_tools()}
    assert "by" not in asyncio.run(tools())["pedigree_corroborate"].input_schema["properties"]

def test_source_identity_is_stable(boundary):
    db, tenant, graph, *_ = boundary
    for _ in range(2):
        record_source(db, graph, tenant, kind="file", uri="docs/rules.md", content_hash="a" * 64)
    assert db.ro_query(graph, "MATCH (s:Source {uri:$u}) RETURN count(s)", {"u": "docs/rules.md"}).result_set[0][0] == 1  # today: 2
```

Counter-assertion once a human credential exists: the same `by="human"` call with it returns `ok`, and `check_action` on the resulting `preserved` node returns `allow` with `preserved_lineage`.
