# F-09 browser and persistence evidence

Builder-operated browser verification, 2026-10-15 21:28–21:35 IST. Independent
read-only browser/API verification is in F-09.md; this file is not independent QA.

Environment: real Uvicorn on 127.0.0.1:8000, real FalkorDB module42201, isolated
random ui-prefixed tenant seeded from committed synthetic S1/S8 fixtures. Tokens
were loaded from an ignored local file and never printed; input cleared on connect.
No git commands or external effects were executed. Main demo tenant was not revoked.

## T3 collaborative browser

`preview_status`, `preview_open`, `preview_snapshot`, focused click/type/evaluate,
and `preview_resize` drove the actual page. Observed:

- Connected with 11 persisted nodes and 3 graph canvas layers, no sample injection.
- S1 source preview: `Would taint 5 · preserve 0 · restore healthy 0`.
- Before confirm, separate database query still returned `[['ok',11]]`.
- Editing reason invalidated confirmation. A new preview was required.
- Confirm refreshed nodes: one revoked source, five tainted descendants.
  DB returned `[['ok',5],['revoked',1],['tainted',5],[None,1]]` (None is a
  Revocation's separate state property; see ADR-006).
- Selecting push + `git push origin main` returned block and full path:
  push → commit → edit → rule → summary → web source, plus untrusted_influence.
- Blame rendered real roots. Token input empty; localStorage/sessionStorage empty.
- Narrow viewport390: settled scrollWidth375 == clientWidth375. Immediately
  after resizing, old Cytoscape canvas briefly exceeded width; resize settled.

T3 connection then failed twice while beginning S8. Raw errors:
`Preview automation click timed out after 15000ms.` and
`No preview automation host is available for click in environment ...`.
A status retry and explicit-tab retry again failed. Switched to Playwright CLI
per the documented browser fallback rule. No claim that failed clicks executed.

## Playwright CLI fallback

Used `npx --yes --package @playwright/cli playwright-cli -s=pedigree-ui`.
An initial run-code syntax attempt and unavailable require failed before page
mutation. Corrected to the CLI's async page function; credentials passed privately,
with code echo suppressed/redacted. Snapshots preceded locator interactions.

Actual live-page checks (exit0):

- Open/connect to the same isolated persisted tenant.
- S8 source preview asserted taint1 and preserve1; confirm succeeded.
- Supported memory status preserved; `git commit -m synthetic` → allow.
- Dependent status ok; `git push` → reverify with untrusted_influence.
- DB after both confirms: ok2, revoked2, preserved1, tainted6, two Revocations.
- Reload required reconnect (no persisted token); preserved state remained.
- Native keyboard focus + Enter selected supported memory. Result:
  `{"focused":{"id":"demo_s8_supported","pressed":"true"},"decision":"allow","width":{"scroll":390,"client":390}}`.
- Screenshots saved locally to ignored output/playwright/ui-desktop.png and
  ui-mobile.png. The desktop screenshot was visually inspected.

Repairs during browser checks: corrected preview count keys to server's
would_taint/would_preserve/would_keep_ok; preserved keyboard focus across list
rendering; retained status fill when a graph node is selected; cleared stale
affected-action reports when selecting another node. Final combined API/QA tests
and scans are recorded in PROGRESS.md.

Limits: CSS viewport emulation, not a physical phone; local service, not deployment;
authored synthetic scenarios, not recorded runtime traces; no shell execution proof.
