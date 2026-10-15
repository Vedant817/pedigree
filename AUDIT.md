# AUDIT — `Vedant817/pedigree` (Graph Hacks: Context for AI Agents)

Audited: Fri 16 Oct 2026, ~00:15 IST. Snapshot = all files fetched through the GitHub connector and verified byte-for-byte by git blob SHA (21 commits, head `83de9da`, 15 Oct 19:10–22:01 IST). Nothing was written to his repo. Everything I could run, I ran, against a real FalkorDB v4.22.1 (own redis-server + `falkordb.so`, ports 6390–6392). Probe scripts and raw outputs are in `probes/`. Anything I could **not** verify is tagged **[UNVERIFIED]**.

---

## 1. Executive verdict (blunt)

Pedigree is a genuinely well-engineered **core** (revoke/blame/gate engine, parameterised Cypher, a correct concurrency barrier, a working hook→capture→gate loop, a clean UI) wrapped in a **submission that does not yet exist**: the repo is private, the README is a stub with no data model, no Cypher, no walkthrough, no video script, no blog, no deployment, no evals — i.e. it currently fails the hackathon's own submission requirements and has none of the "numbers" that are the whole differentiator against five direct competitors. Worse, the headline claim ("cascade-revoke on a big graph") is **false at scale**: a single missing-index-anchor pattern makes revoke O(N²) and it times out above ~15–20k nodes, after which the graph is left half-quarantined and **retrying does nothing**. Roughly **30 % of the value-weighted scope ladder is done** (10 of 23 features marked done, but the done ones are the cheap half); with 63 h to the Sun 3 PM freeze it is recoverable, but only if the next 24 h go to the five fixes in §9, not to new features. As it stands: **top-50 swag plausible if submitted correctly, a track prize unlikely (my estimate 4–8 %), a prize with the fixes + real evals + a crisp demo maybe 12–18 %.**

---

## 2. Scorecard (0–10, evidence-based)

| # | Area | Score | One-line justification |
|---|---|---|---|
| 1 | Completeness vs scope ladder | **4** | P0 ≈ 70 %, P1 ≈ 13 %, P2 0 %, P3 ≈ 15 %; F-08, F-12…F-23 not started |
| 2 | Hackathon rules compliance | **3** | AI disclosure + tracks + FalkorDB-central OK; private repo, no data-model/Cypher docs, no video/blog/deploy, no WALKTHROUGH |
| 3 | Idea / product | **6** | Strong, differentiated thesis; real hook loop works; but capture is shallow, demo is an 11-node toy, and a better-equipped competitor exists |
| 4 | Technical correctness | **5** | Excellent injection discipline, barrier, oracle-verified revoke; but O(N²) queries, stuck-revoke, reinstate bug, bootstrap hole, quota bypass, broken `pedigree mcp` |
| 5 | Evaluation honesty | **2** | No evals exist (F-14 todo). Nothing fabricated (check_numbers passes, 4 trivial values) but docs promise `evals/baselines.py` that does not exist |
| 6 | Business / positioning / resume value | **4** | Real adoption path (Claude Code hook) but README first-screen is empty; no CI, SECURITY.md, lockfile, releases, Dockerfile |
| 7 | Agent process compliance (docs/04) | **5** | Specs, ADRs, consults, red-team on F-10/F-11 are real; F-05/F-06 QA is 2–3 lines of self-certification and PASSed features that don't work |
| 8 | Time risk | **5** (higher = safer) | 63 h to freeze is enough for the must-fix list; risky if OpenCode quota/model access keeps stalling (F-08 already blocked) |

**Overall: 4.2 / 10 — "good engine, no submission."**

---

## 3. Completeness (area 1)

Source: `docs/FEATURES.md`, `docs/05-PHASES.md` ladder, my own runs.

| Tier | Features | Marked done | My effective completion | Notes |
|---|---|---|---|---|
| **P0** (F-01…F-10) | 10 | 9 (F-08 blocked) | **≈ 70 %** | F-03 has 3 real defects, F-06 CLI broken, F-07 only synthetic payloads, F-10 = 11 nodes |
| **P1** (F-11…F-16) | 6 | 1 (F-11) | **≈ 13 %** | no ACL/metrics/logging, no evals, no isolation suite, no deploy |
| **P2** (F-17…F-22) | 6 | 0 | **0 %** | (these are the cut list anyway) |
| **P3** (F-23) | 1 | 0 | **≈ 15 %** | README is 74 lines; AI_DISCLOSURE is half placeholders; no blog/video |
| **Overall** | 23 | 10 (43 % by count) | **≈ 30 % value-weighted** | the missing items are exactly the ones judges can see |

Per-feature effective %, P0: F-01 95 · F-02 85 · F-03 70 · F-04 90 · F-05 75 · F-06 70 · F-07 60 · F-08 0 · F-09 85 · F-10 70.

**Commit history (verified via `list_commits`):** 21 commits, all dated 15 Oct 19:10–22:01 IST (after the 00:01 start → rule "new work" OK on timestamps; author dates are self-reported and can't prove more). The first commit (`d7b3d22`, "skeleton – package, engine, tests (45 green)") is a bulk drop of an already-working engine — that engine descends from the research prototype in the design pack (AI-generated), which **`AI_DISCLOSURE.md` does not say** (see P-030). Nothing since 22:01; repo created 23:48. `docs/PROGRESS.md` cites tag `phase-0` / commit `fd948a0` which is **not in the pushed history** (history was re-created; the evidence trail points at a ghost) (P-033). Secret scan on the tree: PASS (`scripts/secret_scan.py`). **Git history secret scan: [UNVERIFIED]** — I only had the tree; commit `b2d2bcc` says it masked an "AWS-key-shaped" test string "so the history gate stays clean", meaning an earlier commit (`a79e47d` or before) may contain it — run `gitleaks`/`secret_scan --history` on the real clone before going public.

---

## 4. Rules compliance (area 2)

| Rule / expectation | Status | Evidence |
|---|---|---|
| FalkorDB is central | ✅ | all state, traversal, revoke fixpoint, blame paths are Cypher on FalkorDB (`db/queries.py`) |
| New work in hackathon window | ✅ (timestamps) | commits 15 Oct 19:10+; **disclose the design-pack/prototype origin** (P-030) |
| Public / synthetic data | ✅ | `scripts/seed_demo.py`, synthetic payloads only |
| **Repo public** | ❌ **BLOCKER** | currently private; anonymous `git clone` fails (P-001) |
| README: setup | ❌ | `make start-db` fails on Linux/no-Docker (3 separate failures, P-003); no Dockerfile though KNOWN_ISSUES/ADR-001 cite one |
| README: graph data model | ❌ | README has 5 headings; "Why a graph?" is prose; no schema table/diagram (P-002) |
| README: Cypher/algorithms used | ❌ | none shown; Cypher exists only in `db/queries.py` (P-002) |
| Demo video script / video | ❌ | not started (P-005) |
| Live deploy OR full local instructions | ❌ | F-16 todo; local instructions broken (P-003, P-004) |
| Tracks named | ✅ | README "Tracks entered" |
| Honest AI disclosure | ⚠️ | file exists; "what the human did" is `PENDING` placeholders; cites nonexistent `evals/baselines.py`; omits pack-origin (P-030) |
| Human-explainability (WALKTHROUGH) | ❌ | `docs/WALKTHROUGH.md` referenced in README doc-map, file absent (P-005) |
| Blog (side prize) | ❌ | not started |
| Judging guidance: multi-hop depth | ✅ | blame paths, depth slider, 6-hop demo chain |
| Judging guidance: "not in the graph" | ✅ | `NotFoundInGraph` / `not_in_graph` on blame (tested) |
| Judging guidance: LLM never writes Cypher | ✅ | static queries + lint test; **verified** by injection probe `p11` |
| Judging guidance: tool-call trace | ⚠️ | `Trace` exists internally but is **not returned** by `/v1/revoke|blame|gate` or MCP (`grep trace routes/engine.py` → 0 hits) (P-022) |
| Rule 12/13 (human must be able to explain) | ⚠️ risk | decisions/specs authored by agents, AI_DISCLOSURE placeholders; Vedant must be able to narrate the barrier/fixpoint on camera |

---

## 5. Idea / product (area 3)

**Real or toy?** The idea (provenance + cascade revoke + pre-action gate for agent memory, captured from real coding-agent sessions) is real, defensible, and more *systems-y* than most entries. The *implementation* today is an honest **vertical slice**: ingest → revoke → blame → gate over REST/MCP/hook works end to end (probe `p09`: hook payloads → capture → revoke → `deny`). It is **not** production-grade (O(N²), stuck states, no ACL, no persistence story, single-process lock) and the *demo* is a hand-authored 11-node graph.

**Real session capture?** Partially. `adapters/claude/pedigree_hook.py` is a decent stdlib, fail-open, 1 s-timeout hook (✅ works on synthetic Claude payloads, p09). Not demonstrated against a real Claude Code session [UNVERIFIED — I can't run Claude Code here]. No WebFetch/web-search → `Source` capture; Bash file reads are not tracked as `READ`; the OpenCode adapter (F-08) is blocked/absent. So "real capture" is the weakest link of the pitch.

**Cascade revoke / blame / gate:** ✅ semantically correct (300/300 trials vs an independent global-fixpoint oracle, `p02`), ❌ at scale (P-010), ❌ reinstate (P-012), ❌ recovery (P-011).

**Honest comparison:**

| Competitor (README scans in `research/`) | What I verified today (16 Oct 00:1x IST) | Pedigree vs it |
|---|---|---|
| **lineage** (Vaibhaav-Tiwari) | 54 commits, last 15 Oct 21:06 IST; 17 KB README; Dockerfile, docker-compose, `uv.lock`, `eval/`, `tests/`, Next.js `web/`, MCP, `GRAPH.COPY` what-if, real data (745 PEPs); deploy + video "go up Oct 18" | **Ahead of us on polish, data realism, deploy, lock-file, evals folder.** We are ahead only on engine rigor (CAS barrier, oracle-checked revoke, hook capture). Track 3 + Track 2 → they target the same Track 2 judges. |
| **undograph** (Tejas-Sands) | 22 commits, last 15 Oct 20:16 IST, "landing redesign" | similar concept; no MCP/real capture per census; polishing UX |
| **kintsugi** (Itz-Agasta) | 27 commits, HTTP server "live run and repair" | same thesis; WIP |
| MemoRepair / PACMI / Graphiti (prior art, `research/01-prior-art.md`) | not re-verified | MemoRepair = academic repair; Graphiti = temporal KG memory with no revoke/gate. Pedigree's *gate + capture + isolation* is the novelty — **but only if shown with numbers** |

I only verified commit counts/README/tree for the competitors, not their runtime behaviour **[UNVERIFIED]**.

**What a judge sees in 3 minutes today:** a private repo (nothing), then — if public — a 74-line README with no screenshot, no data model, no video, no live link; clone → `make start-db` fails on Linux without Docker; if they get the UI up: a tidy 11-node graph and a revoke preview. The 3-minute story ("poisoned page → agent's memory → blocked `git push`") is *buildable from what exists* but isn't packaged.

---

## 6. Findings

Format: **ID · Title** — Evidence · Why it matters · Exact fix · Effort.

### BLOCKER (submission invalid / headline claim false)

**P-001 · Repo is private.** Evidence: `gh`-less anonymous `git clone https://github.com/Vedant817/pedigree` → "could not read Username"; created private 15 Oct 23:48 IST. Why: judges cannot see it; submission requires a public repo. Fix: make public *after* P-002/P-003/P-030 and a history secret scan (`gitleaks detect` + `scripts/secret_scan.py --history`). **Human-only step.** Effort: 5 min.

**P-002 · README has no graph data model, no Cypher, no algorithms.** Evidence: `README.md` (74 lines, headings: Why a graph? / Quick start / Tracks entered / Documentation map / License); `docs/WALKTHROUGH.md` referenced but absent. Why: explicit hackathon README requirement; also the #1 thing technical judges scan. Fix: add (a) Mermaid schema diagram of Source/Memory/Action/Session/Agent/Revocation + DERIVED_FROM/FEEDS/CORROBORATED_BY/READ with property table; (b) "Cypher & algorithms" section showing the 4 core queries verbatim from `db/queries.py` (revoke root CAS, quarantine fixpoint, compute_final rule, blame shortest path) with 1-paragraph explanation each + why `Node(id)` index/`WHERE m:Memory`; (c) first-screen: one-sentence pitch, 20-s GIF/screenshot, 3 numbers (from NUMBERS.md), 3-command quickstart. Effort: 2–3 h.

**P-003 · README quick-start fails on the judge's likely path (Linux, no Docker).** Evidence (clean copy `/workspace/pedigree-audit/judge`, `probes` log): `make start-db` needs an activated venv, the `localdb` extra and `FALKOR_SO`, none of which README says; with Docker absent it errors after waiting 60 s; README's serve command is the Windows path `.venv/Scripts/python.exe` (`README.md:33`). Why: any "full local instructions" claim must work from a clean clone. Fix: one path that works: `docker compose up` (needs P-004) and a documented no-Docker path (`pip install -e .[localdb]; make start-db-lite`), verified by `scripts/clean_clone_check.sh` run in a fresh `python:3.12` container in CI. Effort: 2 h.

**P-004 · No deployment artefacts; docs claim one.** Evidence: no `Dockerfile`, `docker-compose.yml`, `render.yaml` in tree; `docs/KNOWN_ISSUES.md` #1 and ADR-001 say the "production Dockerfile" exercises the pinned FalkorDB; F-16 `todo`. Why: "live deployment OR full local instructions" is a rule; a claim-vs-reality gap is a credibility hit. Fix: single-container `Dockerfile` (python:3.12-slim + `falkordb/falkordb:v4.22.1` as separate service in `docker-compose.yml`; seed-on-boot with `scripts/seed_demo.py`; healthcheck on `/readyz`; non-root user). Optional: one public deploy (Render/Fly) with a *read-only demo tenant* and admin disabled. Effort: 3 h (compose), +2 h public deploy.

**P-005 · Missing submission artefacts: video script, WALKTHROUGH, blog.** Evidence: no `docs/WALKTHROUGH.md`, `docs/DEMO_SCRIPT.md`, `docs/BLOG.md`; F-23 todo. Fix: see FIX_PROMPT Phase 4. Effort: 4 h agent drafts + human records video (human-only).

**P-010 · Revoke cascade is O(N²); the "100k nodes" claim fails.** Evidence: `db/queries.py:159-160` `Q_SUPPORT_OF = UNWIND $ids AS i MATCH (m:Memory {id:i})-…` — `EXPLAIN` shows *Node By Label Scan* because the unique index is on `:Node(id)`, not `:Memory(id)`. Measured (`probes/p05_scaling.txt`, `p13_output.txt`): revoke cascade 2k nodes 1.1 s → 5k 7 s → 10k 32 s → ≥20k times out at TIMEOUT_MAX; 100k fails (`p05_output_dag100k.txt`). Same defect in `Q_ACTION_DETAILS` (:162), `Q_MEMORY_ARTIFACTS` (:166), `Q_GATE_SUPPORT` (:297): 1000 ids on a 60k-node graph = 3.7–5.5 s each vs **0.01 s** with `MATCH (m:Node {id:i}) WHERE m:Memory` (`p13`, `p05c`). Why: the gate query is on the hot path and the headline benchmark (E1/E2: 10k–100k) cannot be run; research asserted this scaled. Fix: rewrite the four queries as above, add `tests/perf/test_label_anchor_lint.py` that fails on any `MATCH (x:Label {id:` in `queries.py`, add a 20k-node revoke regression test with a 20 s ceiling. Effort: 1 h. **Highest-value fix in the repo.**

### CRITICAL

**P-011 · A failed/crashed revoke strands the graph and cannot be retried.** Evidence: `engine/revoke.py:136` returns `idempotent: True` when the root is already `revoked`/`running`; `resume_incomplete` (`revoke.py:299`) is never called outside tests. Probe `p06_output.txt`: 20k-node revoke times out → nodes left `quarantined`, `Revocation.status=running`; second `revoke()` returns idempotent no-op; nodes stay quarantined forever. Why: any timeout (see P-010) or crash corrupts a tenant permanently — contradicts the "crash-safe" claim in ADR. Fix: call `resume_incomplete` at start of `revoke()` for the same tenant and on app startup; make the idempotent branch resume when `running`; test: kill after chunk 1, restart, assert final statuses equal oracle. Effort: 2 h.

**P-012 · `reinstate` silently un-revokes independently-revoked descendants.** Evidence: `probes/p03_output.txt` — 22/150 randomized trials differ from the oracle. Deterministic repro (section D of `p03_reinstate_and_order.py`): `A(source) → B(memory) → Cc(memory)`; `revoke(A)`, then `revoke(B)`; before: `A=revoked, B=revoked, Cc=tainted`; after `reinstate(A)`: **`A=ok, B=ok, Cc=ok`** (B was revoked on its own and must stay revoked). `check_invariants` returns `[]`, so the damage is also undetected. Why: silent safety regression of the very property the product sells. Fix: `Q_REINSTATE_RESET` must only reset nodes whose sole taint root is the reinstated one; simplest correct approach: after removing the Revocation, recompute status for the affected subtree with `compute_final` treating *all remaining active revocations* (and the node's own `revoked` flag) as roots; extend `check_invariants` with "no node `ok` that is itself a revoked root or has a revoked ancestor without trusted support"; add a property test using the p03 oracle. Effort: 3–4 h.

**P-013 · Unauthenticated admin bootstrap + weak admin auth.** Evidence: `api/routes/admin.py:10,20` — when `registry.has_tenants()` is false, admin endpoints skip the token check; probe `p01_output.txt` creates a tenant and lists tenants with no credentials on a fresh server. Admin token compared with `==` (non-constant time); `.env.example` ships `change-me-admin`. Why: a public deploy that boots before the seed → first caller owns the box. Fix: require `ADMIN_TOKEN` always (refuse to start if unset/default outside `PEDIGREE_ENV=dev`), `hmac.compare_digest`. Test: fresh registry + no header → 401. Effort: 45 min.

**P-014 · Quota (`node_cap`) bypass via `/v1/events`.** Evidence: `p07_output.txt` — tenant with `node_cap=5` holds 55 nodes after one `/v1/events` post; events/sessions/corroborate paths don't call the cap check. Why: resource exhaustion; also invalidates the "limits" claim in F-05 QA. Fix: single `enforce_quota(tenant, add=n)` in ingest engine used by all write paths + count query cached per request. Effort: 1.5 h.

**P-015 · The agent can launder trust and revoke itself.** Evidence: `probes/p12_output.txt` — one `corroborate(by="human")` using a self-minted `Source(kind=human, integrity=trusted)` flips a poisoned memory from `tainted` to `preserved` after revoke and downgrades the gate from *block* to *reverify*. MCP tools take the same bearer token for read/write/revoke/reinstate/corroborate (`mcp_server.py`), so a prompt-injected agent has the same powers as the operator. KNOWN_ISSUES #11 admits it ("accepted"). Why: undermines the core "trust only human/scanner" ADR-007 and the security pitch; a security judge will find it in minutes. Fix: two token roles — `agent` (ingest/read/gate only) and `operator` (revoke/reinstate/corroborate-human/mint trusted sources); MCP exposes only the agent role; trusted-integrity sources and `by=human|scanner` require operator role; tests in `tests/security/`. Effort: 3 h.

**P-016 · `pedigree mcp` crashes; no `/mcp` mount despite docs/config.** Evidence: `cli.py:180` calls `build_mcp(settings, default_tenant_id=…, default_tenant_token=…)` but `mcp_server.py:208` is `build_mcp(db=None, settings=None, …)` → `settings` lands in `db`; running `python -m pedigree.cli mcp --transport stdio` ends in `AttributeError: 'Settings' object has no attribute 'try_query'` (reproduced). `opencode.json:6` points at `http://127.0.0.1:8000/mcp`, README says the server serves "API + MCP + UI", but `api/app.py` mounts no MCP app (`GET /mcp` → 404, reproduced on my server). MCP works only when constructed through the Python API (`p08`: stdio + streamable-http). `docs/qa/F-06.md` is 3 lines and says PASS. Why: MCP is the Track-1 headline surface and the documented entry point is dead. Fix: `build_mcp(settings=settings, …)` (keywords), mount the streamable-HTTP app under `/mcp` (or document a separate port and fix `opencode.json`), add a subprocess test that launches `pedigree mcp --transport stdio` and calls a tool with the real MCP client. Effort: 1–2 h.

**P-017 · "Real session capture" is thin and unproven.** Evidence: `tests/` use hand-written payloads only (`tests/fixtures` does not exist; F-07 spec promised recorded fixtures); F-08 OpenCode `blocked`; `adapters/claude/pedigree_hook.py` maps Bash/Read/Write/Edit but not WebFetch/WebSearch as Sources; session-wide taint makes later benign actions `ask`; `\bssh\b` regex flags `cat ~/.ssh/config` as irreversible/high (`p09`). Why: the differentiator over 5 competitors is capture from real runs; judges will ask "did you capture a real Claude Code session?" Fix: record 2–3 real Claude Code sessions (human, 20 min) → sanitised fixtures → fixture-replay tests; add WebFetch/WebSearch → `Source(kind=web)` mapping and Bash `cat/curl` read edges; narrow taint to *sources read in this session that were revoked*; tune classifier. Effort: 4 h + 20 min human.

**P-006 · No evaluation harness or numbers (F-14/F-20 todo).** Evidence: no `evals/`, no `tests/fixtures`; `docs/NUMBERS.md` has 4 trivial allowed values; `AI_DISCLOSURE.md` cites `evals/baselines.py` which doesn't exist. Why: the pack's whole honesty/differentiation story ("blast-radius containment vs naive baselines, with CIs") has zero data. Competitors have an `eval/` folder. Fix: Phase 3 of FIX_PROMPT (minimum E1 containment + E2 latency scaling, 3 baselines, oracle, 20 seeds, CI, `make eval` → NUMBERS.md → README via `check_numbers`). Effort: 6–8 h (after P-010).

**P-007 · QA is partly self-certification and docs make false claims.** Evidence: `docs/qa/F-05.md`, `F-06.md` are 2–3 lines each; F-06 PASS coexists with P-016; F-07 "QA" was a role-switch by the builder (`PROGRESS`, F-01 entry "role-switch verification recorded"); features marked done have no adversarial probe output. Why: docs/04 §2 step 5 requires independent QA with commands + real output; rule 13 risk. Fix: re-run QA properly for F-03/F-05/F-06/F-07 with my probes as seed cases (copy `/workspace/pedigree-audit/probes/` into `tests/qa/`), real outputs pasted. Effort: 3 h.

### MAJOR

**P-020 · Rate limiting is wrong and auth is O(#tenants).** Evidence: `api/auth.py:23 _gate_rate` called in addition to a second counter → 60 writes/min allowed vs 120 advertised (`p07`); reads share the write bucket; `registry.resolve` (`registry.py:94-104`) loops `list_tenants()` on every miss — latency 3 ms→75 ms at 307 tenants (`p07`); no failed-auth throttle; in-memory per process. Fix: index tokens by SHA-256 digest (single `MATCH`), separate read/write buckets, failed-auth backoff per IP. Effort: 2 h.

**P-021 · Input validation holes leak exception text / 500s.** Evidence: `api/app.py:33` and `mcp_server.py:25` return `str(exc)` for unhandled errors; `/v1/events` with `"conf": 5` or `"artifacts": 5` → TypeError → HTTP 500 and the connection closes; `derived_from: "abc"` is iterated per character; NUL/newline in `uri` → `PedigreeError: database error` (`p11`). Fix: pydantic models with `extra=forbid`, bounds, `list[str]`; generic handler returns `{"code":"internal","request_id":…}` and logs the detail. Effort: 2 h.

**P-022 · No observability; tool-call trace not exposed.** Evidence: `/metrics` (`routes/metrics.py`) serves only default process metrics and is unauthenticated; no `pedigree_*` series (AT2.5 unmet); zero `logging` usage in `src/`; `Trace` object exists (`db/client.py`) but `routes/engine.py` never passes/returns it. Why: the judging guidance asks for visible tool-call traces; F-13 todo. Fix: return `trace` (ops, ms, rows) in revoke/blame/gate responses and MCP results; add `pedigree_query_seconds`, `pedigree_revocations_total`, `pedigree_gate_decisions_total`; JSON structured logs with `request_id`+tenant; protect `/metrics`. Effort: 3 h.

**P-023 · Tenant isolation is application-level only and untested as a suite.** Evidence: all cross-tenant API probes → 404 (`p07`, good) but `Settings` has a `pedigree_db_acl` flag that is unused, no per-tenant FalkorDB ACL (F-13), no `tests/isolation` suite (F-15 todo). Fix: at least a hypothesis/thread isolation test using my p04/p07 as base; optional ACL users. Effort: 3 h (tests), 4 h (ACL).

**P-024 · Late children stay `quarantined` forever.** Evidence: `p04_output.txt`: in the threaded runs, e.g. run 11 (358 nodes) ends with 54 nodes `only_quarantined_not_resolved` (0 leaks of `ok`/`preserved`) — children written during a revoke are born `quarantined` and never resolved (revoke only resolves nodes it discovered; there is no reconciler). Fix: after each revoke verify step, re-scan `quarantined` with no `running` revocation and run `compute_final` on them; add a `pedigree reconcile` command and an invariant. Effort: 2 h.

**P-025 · Import-time DB side effects.** Evidence: `api/app.py:82 app = create_app()` and `mcp_server.py:214-225 _build_default()` connect and create indexes at import; with the DB down `python -c "import pedigree.api.app"` → `RuntimeError: index creation failed … Connection refused` (reproduced). Why: breaks tooling, tests, `uvicorn --factory`, and hot reload. Fix: use `create_app` as a factory (`uvicorn pedigree.api.app:create_app --factory`) and lazy `get_default()`. Effort: 1 h.

**P-026 · `ensure_schema` runs twice per request; per-tenant lock is in-process only.** Evidence: `p07` timing; `engine/revoke.py` uses `threading.RLock` keyed by tenant — with `--workers N` the CAS barrier still protects correctness at DB level but the RLock gives no cross-process exclusion for compute/write phases **[partially verified: single-process threads only]**. Fix: cache schema-ready per graph; document single-worker or use the CAS barrier + `Revocation` lease with TTL. Effort: 2 h.

**P-027 · UI is a 11-node toy with no path/trace strip.** Evidence: `scripts/seed_demo.py` (11 nodes), `src/pedigree/ui/app.js`; screenshots `probes/ui_*.png`. Works and looks professional (preview, depth slider, evidence panel), but F-21 todo, no revoke animation, token must be pasted. Fix: seed a second "realistic" tenant (≈300 nodes from a synthetic coding-agent trace), a one-click "Demo" auto-login for the read-only demo tenant, path highlight on blame. Effort: 4 h.

**P-028 · No CI, lockfile or reproducible environment.** Evidence: no `.github/`, `uv.lock`/`requirements.lock`; `pyproject.toml` `fastapi>=…`, `uvicorn>=…`, `mcp>=2,<3`. Why: clean-clone reproducibility; lineage ships `uv.lock` + Dockerfile. Fix: `uv lock` or `pip-compile`, GitHub Actions running `make check` against `falkordb/falkordb:v4.22.1` service. Effort: 1.5 h.

### MINOR

- **P-029** `Bearer  token` (two spaces) accepted; admin can create tenants with invalid ids / `node_cap ≤ 0`; `/docs` and `/openapi.json` public (fine for demo, document); read/write timeout settings > `TIMEOUT_MAX` (60 000) are not validated and are rejected by the server at runtime. Effort 1 h total.
- **P-030** `AI_DISCLOSURE.md`: "human did" sections are `PENDING`; cites nonexistent `evals/baselines.py`; **does not state that the design pack and the core-engine prototype were AI-generated before the event**; model names listed as used must match reality **[UNVERIFIED]**. Fix: Vedant writes it in his own words (human-only), agent supplies a fact sheet. Effort 45 min.
- **P-031** Session/Revocation nodes may be used as `derived_from` parents (`p11`: `session_as_parent` OK) — model hole; restrict parents to Source/Memory/Action.
- **P-032** Dead code: `REGISTRY_GRAPH`, `Q_PAGERANK_SOURCES`, LLM settings in `config.py` unused. Remove or implement F-18.
- **P-033** `docs/PROGRESS.md` references `phase-0` tag / `fd948a0` not in history; no tags/releases at all. Re-tag `phase-0`, `v0.1.0`.
- **P-034** Repo hygiene: no `SECURITY.md`, `CONTRIBUTING`, issue/PR templates, CI/status badges; the 140 KB design pack + competitor research committed under `docs/` makes the repo read as AI scaffolding and exposes strategy; move to `docs/design/` or drop from public tree (human decision).
- **P-035** README Windows serve command; `.env.example` default admin token (see P-013).
- **P-036** Hook is caller-asserted (`source_kind`, `integrity`); acceptable with P-015 roles, document trust model.

---

## 7. What is actually good (credit where due)

- **Cypher discipline:** every query static + parameterised; lint test enforces it; injection probe `p11` (`'}) DETACH DELETE n //` in id and text) → rejected/stored as data, node count unchanged.
- **Revoke semantics correct** on 300/300 randomized DAGs vs an independent oracle (`p02`); CAS barrier holds under 12 threaded runs, no leaks (`p04`).
- **Tenant isolation at API holds** (all cross-tenant probes 404).
- **Gate design** (allow/warn/reverify/block, trust only from human/scanner, hook allow/ask/deny mapping) is thoughtful and the hook→capture→revoke→deny loop works end to end (`p09`).
- **254 tests pass, 3/3 repeated runs, ~9.6 s, no flakiness**; ruff-clean; secret scan passes on the tree.
- **Honest KNOWN_ISSUES.md**, ADRs, a real consult + red-team record for F-10/F-11.
- **UI works** (screenshots), uses `textContent`, keeps token in memory only.
- `check_numbers` gate exists and passes — the *mechanism* against fabricated numbers is in place; it just has nothing to guard yet.

---

## 8. Voices

**What a judge would say (≈ 3 min):** "Interesting and technically serious idea — cascade-revoke with a gate is the right abstraction. But where is the data model, the video, the numbers? I can't run it in 5 minutes on my laptop. The demo graph has 11 nodes; the competitor next door has 745 PEPs, Docker and an eval folder. Show me it on a thousand nodes with a measured containment result."

**What a recruiter would say (60 s):** "Repo is private/blank README → no signal. If public with fixes: strong systems-engineering signal (concurrency barrier, oracle testing, red-team docs); the bulk-commit-then-silence history and AI-scaffold docs make me ask 'what did *you* write?' — you must be able to explain the barrier and the fixpoint cold."

**SDE hiring manager probes to expect:** Why is revoke O(N²) — and how did you find it? What happens if the process dies at chunk 3? How do you stop an agent granting itself human trust? Why one graph per tenant and what does FalkorDB cost per graph? What is your containment number vs a naive baseline and its CI?

---

## 9. Win odds (my honest estimate; not verified by any judge data)

| Outcome | Now | After must-fix list + evals + packaging |
|---|---|---|
| Valid submission accepted | 20 % (private repo, README gaps) | 90 % |
| Top-50 / swag tier | 25 % | 70 % |
| Track prize (Track 1 or 2) | 3–5 % | 12–18 % |
| Blog side-prize | 0 % | 5–8 % |

Reasons: the memory-repair/provenance cluster has ≥ 8 repos (census) and lineage is ahead on polish; our edge (rigor + capture + gate) is invisible without measured evals and a crisp demo.

---

## 10. Time plan (now = Fri 16 Oct 00:15 IST; freeze Sun 18 Oct 15:00 IST ≈ 62 h; submission deadline 23:59 ≈ 71.7 h)

Ordered must-fix list (details + acceptance tests in `FIX_PROMPT.md`):

1. **P-010** label-anchor rewrite (1 h) → unlocks everything else.
2. **P-011, P-012, P-024** revoke robustness (6–7 h).
3. **P-013, P-014, P-015, P-021** security (7 h).
4. **P-016, P-025, P-003, P-004** runnable & deployable (7 h).
5. **P-006** minimum evals E1+E2 (6–8 h).
6. **P-002, P-005, P-030, P-017** docs, WALKTHROUGH, disclosure, real capture fixtures (8 h + human 1 h).
7. Public + video + blog (human, Sat night–Sun).

Cut (in order, per 05-PHASES): F-22 → F-19 → F-21 extras → F-17 → F-18 → E4b → F-12 → second runtime adapter → E3b. **Do not cut:** P-001…P-006, P-010…P-016.

Realistic budget: Fri 00:15–Sat 06:00 fixes 1–4 (≈ 22 h of agent time, parallelisable); Sat 06:00–Sun 15:00 evals, docs, UI seed, QA, video prep. Biggest schedule risk: the OpenCode free-tier/model stall that already blocked F-08 — switch the builder model before starting.

---

## 11. Verification limits (what I did not / could not verify)

- Docker paths (no Docker on box); Windows commands; a real Claude Code or OpenCode session; Git-history secret scan; `docs/pack/*` and `docs/qa/redteam-*` full contents (read via connector, not exhaustively); hosted deployment (none exists); competitor runtime behaviour; AI model names in disclosure.
- Perf numbers are from this box (shared, single core share) — absolute times will differ, the O(N²) shape and the 300× fix will not.

Artefacts: `probes/p01…p13_*.py` + `*_output*.txt`, `probes/ui_*.png`, snapshot in `repo/`.
