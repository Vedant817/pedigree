# F-11 - Gate: `check_action` + REST `/v1/gate` + MCP + hook deny/ask + `policy.yaml` classifier

Status: done | Tests: implemented | QA: docs/qa/F-11.md PASS; redteam-F-11.md PASS
Implements docs/01 §6.6 as amended by consult 006 (`docs/consults/006-gate-ancestor-scope/decision.md`,
ADR-007). **ADR-007 supersedes the literal "or ancestor" wording of §6.6 rule 1.**

## Behaviour

`check_action(db, gname, action, *, relied_on=None, session_id=None, policy_path=None,
max_depth=12, record=False, tenant=None, trace=None) -> dict` (read-only; no writes unless
`record=True`, which writes one Action node with `decision`).

1. **Inputs.** `tool` (str, required), `summary`, `effect` (`reversible|irreversible|unknown`),
   `risk` (`low|medium|high`), `audience` (tags), `relied_on` (ids, <= 64), `session_id`,
   `policy_path`. Missing `effect`/`risk` come from the `policy.yaml` classifier (docs/01 §7.3).
   Missing `audience` = `['local']` (`['public']` for network/push/publish tools, per §6.6).
2. **Anchor set.** `relied_on` if given, else the session read window (last K distinct READ
   targets, `Q_READ_WINDOW`). Neither -> `allow` + `warning:no_lineage` (never block a fresh
   session; §6.6 rule 4).
3. **One chunked read** of the anchor set (`Q_GATE_NODES`: id, status, low_integrity, conf_eff,
   taint_parent, kind). Missing ids -> `reverify` [`not_in_graph`] (we refuse to claim "safe").
4. **Rule 1 `tainted_ancestor` (ADR-007 B).** Anchor with status
   `revoked|tainted|quarantined` -> `block` if risk >= `medium` else `warn` (allow + reason).
   **1b:** anchor with status `preserved` whose `CORROBORATED_BY` edges are all `by='agent'`
   (or absent `by`) is gated exactly as `tainted`; trusted support (`by` in `human|scanner`)
   passes and adds an info reason `preserved_lineage` naming the supporting source.
   `reasons[].path` = the anchor id followed by the `taint_parent` chain (bounded 12 hops) to the
   revoked root; direct revoked anchor -> `path=[id]`.
5. **Rule 2 `confidentiality_violation`.** Union of `conf_eff` over anchors minus `audience` ->
   `block` (rule 2 of the spec; labels already exist, scenario S6 is F-12).
6. **Rule 3 `untrusted_influence`.** `low_integrity` and (`effect='irreversible'` or `risk='high'`)
   -> `reverify`.
7. **Rule 3b `preserved_untrusted_support` (ADR-007 case-2 closure).** `effect='irreversible'` or
   `risk='high'` and an anchor's ancestor closure contains a `preserved` node with untrusted-only
   support -> `reverify`, path = anchor -> ... -> that preserved node -> revoked root.
8. **Rule 4 `not_in_graph`.** Any anchor id not in the graph -> `reverify`. Read window case:
   `relied_on` empty but the window holds a `revoked|tainted|quarantined` node -> `reverify`
   (floor; never silent allow).
   High-risk/irreversible ancestry with a frontier beyond `max_depth` -> `reverify` with
   `lineage_truncated`; bounded traversal must not silently establish trusted containment.
9. Verdict order `allow < warn < reverify < block`; first match wins per rule, `reasons[]` carries
   every fired rule; `checked` = number of anchors inspected. Response:
   `{decision, reasons[{code,node_id,path,detail}], checked: int, hook, would_verify[]}`.
10. **Hook mapping.** `block -> {"permissionDecision":"deny"}`, `reverify -> "ask"`,
    `warn/allow -> "allow"` (+ reason text) for Claude Code `PreToolUse`
    (`adapters/claude` JSON contract, docs/01 §8.1); the same field drives the OpenCode plugin (F-08).
11. **`policy.yaml`** (committed default, `PEDIGREE_POLICY_FILE`): deterministic classifier -
    ordered rules `{tool: regex, match?: regex on summary/command, effect, risk, audience?}`;
    missing policy = built-in defaults. `policy_path` is accepted only from server configuration,
    never from the request body (arbitrary file read).
12. **`record=True`** stores the Action via `record_action(...)` with the verdict as `decision`
    and the anchor set as `relied_on` (so the graph records what the gate saw). Missing anchors or
    Session skip recording without a write; return the verdict plus `recording_error` with
    `code: not_in_graph` and missing ids/session_id. `action_id` appears only after success.
    REST/MCP apply node quotas to recording.

## Data model / Cypher touched
- New: `Q_GATE_NODES` (extended node read incl. `conf_eff`/`taint_parent`), `Q_GATE_SUPPORT`
  (`CORROBORATED_BY` with `by`), policy file. Taint chains reuse `Q_GATE_NODES`.
- Reused: `Q_READ_WINDOW`, `Q_ANCESTORS`, `Q_NODE_DETAILS`, `Q_TAINT_PARENT`, `record_action`.
- No schema change. No writes on the decision path.

## Invariants
- I1 (load-bearing): after any revocation, no `ok` node has a `DERIVED_FROM` parent with status
  `revoked|tainted|quarantined` -> new `Q_INV_OK_HAS_NO_BAD_PARENT` in `check_invariants`.
- I2: the decision path performs no `db.query` writes (asserted in tests via node snapshot).
- I3: block/warn mapping is exactly `risk in {medium,high}` -> block, `low` -> warn.
- I4: `path` <= 12 hops, ends at a revoked node or documents `taint_parent missing`.

## Acceptance tests (write first)
- `tests/unit/test_gate.py`: risk/verdict mapping; reason ordering; policy classifier table
  (git push/npm publish/ssh/rm -rf -> irreversible+high; git commit -> medium; default reversible/low);
  audience defaults (network -> public); hook mapping; `no_lineage`.
- `tests/integration/test_gate_integration.py` (real FalkorDB, S8 + S1 shapes):
  1. `gate_preserved_dependent_allows` (THE distinguisher): bad source -> M1 corroborated by a
     **human-scanner-attested** doc -> `preserved`; M2 derived from M1 -> `ok`; action relies on M2,
     risk=high -> `allow`.
  2. `gate_agent_asserted_support_is_not_trusted`: same shape but `by='agent'` -> `block` at
     medium+ / `warn` at low, code `tainted_ancestor`, path to the revoked root.
  3. `gate_tainted_medium_blocks` / `gate_tainted_low_warns`, `gate_quarantined_midflight_blocks`,
     `gate_revoked_source_direct`.
  4. `gate_ok_descendant_of_untrusted_preserved_reverify_at_high` (case-2 closure): risk=high ->
     `reverify` with `preserved_untrusted_support` and the path; risk=medium (reversible) -> `allow`.
  5. `gate_missing_id_reverify`, `gate_no_relied_on_allows_with_warning`,
     `gate_read_window_floor_reverify` (tainted node in window, `relied_on` empty).
  6. `gate_confidentiality_blocks` (union tag not in audience) and passes with a superset audience.
  7. `gate_record_true_writes_action_with_decision`; `gate_is_read_only` (snapshot proof).
  8. `inv_ok_node_has_no_bad_parent` in `test_schema.py` (negative: hand-corrupt -> detected).
- `tests/security/test_security_F11.py`:
  1. laundering repro from the red team (mint `file` source, agent-asserted corroboration,
     revoke the rules file, `git commit`) -> not `allow`.
  2. `CorroborateRequest`/MCP default `by` is `agent` (401-free path); explicit `human` passes
     only when the caller asks.
  3. request-body `policy_path` is rejected with 422 (no arbitrary file read); unknown policy file ->
     built-in defaults, never 500.
  4. `relied_on=[]` with a tainted read window is not `allow`.
  5. oversized `relied_on` (> 64) -> 422; `audience` oversize -> 422.

## Security notes
- Parameterised Cypher only; ids validated (`validate_id`); depth clamped to `LIMITS["depth_max"]`.
- `policy_path` is server configuration (env), never client input.
- Verdict logic is deterministic and free of LLM calls; reasons carry paths as evidence.

## Evidence needed
- pytest unit+integration+security green; `make check` green; QA independent re-run and red-team
  round 2 with the laundering repro.

## Capture and authority limits

Claude adapter verification uses synthetic payloads and a real localhost HTTP subprocess;
installed Claude Code execution remains unverified. Hook failures are fail-open. See the
adapter guide for capture coverage. Matching policy rules can supply audience; explicit
action audience takes precedence. Human/scanner attestation is a caller assertion pending
F-13 role separation; a bearer token alone does not prove human authority.
