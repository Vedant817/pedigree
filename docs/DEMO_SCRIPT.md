# Demo script

DRAFT for a human to record. This file is not a recording, and it is not evidence
that a clean-clone demo was filmed. Keep the operator token off camera. If a live
step does not return what this script says, stop and show the fallback. Do not
narrate a result the screen did not show.

Every measurement below is in `docs/NUMBERS.md`. The six-node chain is
`demo/scenarios/S1.json`. Commands match `docs/WALKTHROUGH.md`.

## 0:00 Pitch

"Pedigree is git blame and git revert for what an AI agent believes. When a page
the agent already used turns out to be wrong, this shows what it believed and did
because of that page, and it keeps a belief that still has independent support."

## 0:20 Three measurements

Say these E1 figures, and say they come from generated lineage graphs, not from a
recorded agent session. Recall `1.0`. Over-invalidation `0.0`. Explicit
preservation-status sensitivity `1.0`. If there is time, add one contrast: the
full-cascade baseline over-invalidates `0.2777` in its deepest generated cell.

## 0:40 Connect

Open the workspace the README quick start already started. Paste the operator
token off camera. The graph on screen should be the seeded `demo` tenant.

Fallback: if the server is down, open `demo/scenarios/S1.json` and read
`expected_after_revoke` and `expected_push_blame_path`. Say that this is the
fixture, not a live revoke.

## 1:00 The six nodes

Point along the chain, child under parent:

- `demo_s1_web`, the synthetic page
- `demo_s1_summary`, a memory from that page
- `demo_s1_rule`, a memory from the summary
- `demo_s1_edit`, a low-risk edit that relied on the rule
- `demo_s1_commit`, a medium-risk commit that relied on the edit
- `demo_s1_push`, a high-risk irreversible push that relied on the commit

Say that this chain has no independent corroborating source, so preservation will
not fire. The push did not run git. The summary in the fixture says so.

## 1:30 Dry run, then revoke

```bash
curl -s -X POST "$BASE/v1/revoke" -H "$H" -H 'Content-Type: application/json' \
     -d '{"root_id":"demo_s1_web","reason":"poisoned page","dry_run":true}'
```

Read the counts the server returned. Then confirm:

```bash
curl -s -X POST "$BASE/v1/revoke" -H "$H" -H 'Content-Type: application/json' \
     -d '{"root_id":"demo_s1_web","reason":"poisoned page"}'
```

Expect the page `revoked` and the other five nodes `tainted`. If the JSON says
otherwise, use the fallback file and do not talk over it.

## 2:15 Blame

```bash
curl -s "$BASE/v1/blame/demo_s1_push" -H "$H"
```

The path to narrate, child first, is `demo_s1_push`, `demo_s1_commit`,
`demo_s1_edit`, `demo_s1_rule`, `demo_s1_summary`, `demo_s1_web`. That chain is
the stored `taint_parent` links. It is not a Cypher `shortestPath`, and it is
not capped by `max_depth`.

## 2:40 Gate

```bash
curl -s -X POST "$BASE/v1/gate" -H "$H" -H 'Content-Type: application/json' \
     -d '{"action":{"tool":"Bash","summary":"git push origin main","effect":"irreversible","risk":"high"},
          "relied_on":["demo_s1_summary"]}'
```

This call names `relied_on`. The summary is tainted and the risk is high, so the
decision to expect is `block`. A low-risk action with the same explicit parent
would be `warn`, not `reverify`. `reverify` replaces that warning only when the
parent list was filled from the session read window. An empty parent list is
`allow` with `warning:no_lineage`. Do not describe those other cases unless you
run them.

## 2:50 Stop

"This contains, explains, and reverts. It does not detect a bad page, and it
does not undo a push that already left the machine. The hook has not been
proven against an installed Claude Code session."

Cut. The GIF and the recording are still human work.
