# Gate API

`POST /v1/gate` requires the tenant bearer token. Example body:

```json
{
  "action": {"tool": "Bash", "summary": "git push origin main"},
  "relied_on": ["memory-id"],
  "session_id": "session-id",
  "record": false,
  "max_depth": 12
}
```

Empty/omitted `relied_on` uses the session's distinct read window. No recorded lineage
returns `allow` with `warning:no_lineage`; this is not a claim that the action is safe.
Missing ids return `reverify`. Verdicts are `allow`, `warn`, `reverify`, `block`, with the
most restrictive fired rule winning. Reasons carry node ids and bounded evidence paths.
Incomplete high-risk ancestry requires re-verification.

The response contains `decision`, `reasons`, `checked`, `would_verify`, `effect`, `risk`,
and `hook` (full Claude `hookSpecificOutput` JSON). `block` maps to `deny`, `reverify`
to `ask`, and other verdicts to `allow`.

Optional recording returns `action_id` on success. Unknown anchors/session skip recording
and return `recording_error` while preserving the verdict. Node quotas apply to recording.
Unknown request fields are rejected, including `tenant` and `policy_path`. Operator policy
comes from `PEDIGREE_POLICY_FILE`; ordered regex rules configure effect, risk and audience.
Request action may explicitly supply effect/risk/audience. Missing policy uses built-in defaults.

MCP tool `pedigree_check_action` takes flat action fields plus token, relied_on, session_id,
max_depth and record. It returns the normal `{ok, result}` envelope. No client-selectable
tenant or policy file is exposed by this tool.

`by` defaults to `agent` on all corroboration interfaces. Explicit human/scanner values are
caller assertions pending role separation; see KNOWN_ISSUES. Gate results are snapshots,
not reservations: a revocation can change the state before an action executes.

Claude setup, capture support and fail-open behavior: [adapter guide](../../adapters/claude/README.md).
