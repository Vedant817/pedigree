# F-09 — Lineage workspace

Status: done after combined checks. Static HTML/CSS/JavaScript, vendored Cytoscape per architecture.

## Behavior and contract

At `/`, connect with tenant token held in page memory only. No credentials in URL,
storage or console. Show actual persisted sources/memories/actions, their statuses and
DERIVED_FROM/CORROBORATED_BY edges; never seed or mock in the browser. An empty graph
explains how to capture or seed. Disconnect clears all graph/detail data.

New authenticated `GET /v1/graph/view?limit=500` returns bounded nodes, edges, truncated,
and query trace. Limit 1..1000; edges limited to 4000 and must reference returned nodes.
No text, summaries, content hashes, token, tenant override or raw database entities returned.
Nodes include id,type,status,kind,title,uri,tool,low_integrity. Source URI/title are own tenant
data rendered with textContent. All queries static and parameterized.

Choose a node by keyboard accessible list or canvas; query blame/impact at depth1..12.
Show paths, impacted actions and explicitly irreversible effects. Revoke is enabled only
for Source/Memory. Preview is read-only dry_run, shows impact and counts; confirmation
binds root, reason and current connection. Clear stale preview when selection/reason/depth
changes. Confirm performs POST /v1/revoke then refreshes persisted data. Revert list is
advice only; UI never runs shell commands. Failed requests retain explanatory error state,
disable confirm and show no success. Gate form uses current selection and real /v1/gate.

## Design

Palette: ink #20374b, ocean #176d89, frost #eef5f8, paper #ffffff,
amber #a96808, danger #ad3549; preservation teal #177c69. Bahnschrift headings,
Segoe UI body and Consolas metadata, all local/offline. Desktop: source rail, graph
canvas, evidence inspector. Mobile: stacked panels and keyboard-accessible node list.
Signature: directed lineage map with typed nodes, independent-support dashed links,
and readable status badges. No external fonts, build step or remote browser dependencies.

## Verification

Write failing API tests for authenticated bounded graph feed, edge closure, truncation,
wrong tenant, static assets and package inclusion. Verify real browser connect/graph/select/
dry-run/cancel/confirm/reload/gate plus narrow viewport and keyboard access. Independent
QA + trust-boundary review required before done. No claim of UI proof from API tests alone.

Evidence: docs/qa/F-09.md (independent read-only browser/API QA),
docs/qa/redteam-F-09.md (boundary review), docs/qa/F-09-browser.md (builder destructive
browser journey plus separate persisted DB queries). Screenshots remain local/ignored.
