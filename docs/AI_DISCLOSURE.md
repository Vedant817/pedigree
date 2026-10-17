# AI disclosure (fact sheet)

Status: complete except the **human-voice fields** marked `[EDIT: ...]`, which only
Vedant can fill in. The tools below are what this repository can show. No hosted
CI run and no Render deployment are claimed (`docs/PROGRESS.md`).

## 1. Tools and models used

| Tool | Role in this project | Used by |
|---|---|---|
| OpenCode (run through T3 Code) | coding agent harness; multi-agent orchestration | entire build |
| [EDIT: model name(s) actually used, e.g. provider/model] | orchestrator, builders, QA, red-team, architect, eval statistician, tech writer, domain researcher | entire build |
| Git, local repository | version control | entire build |
| GitHub Actions | not used; this tree does not claim a hosted CI run | — |
| Render | not used; deployment remains a human step | — |

Model names are filled in by the human; they are not guessed here.

## 2. What was AI-generated

- **The design pack and the core-engine prototype that seeded commit `d7b3d22`
  ("chore: skeleton - package, engine, tests (45 green), docs, scripts") were
  AI-generated before coding began** (per ADR-000 / the pack in `docs/pack/`).
- Most of the code, tests and first drafts of the documentation, authored by the
  agent roles listed in §1 under specifications and acceptance tests written in
  `docs/features/` and `docs/fixes/`.
- Synthetic evaluation data and baselines in `evals/` (seeded, no real user data).
- The demo tenant seed and scenario scripts.

## 3. What the human did  (fill in your own words; do not leave blank)

- [EDIT: what you personally designed — e.g. the lineage/revoke/gate model,
  the tenancy and trust-boundary decisions, the eval design, the scope cuts]
- [EDIT: what you personally verified — e.g. ran `make check`, `make eval`,
  `make dogfood`; reviewed every Cypher query in `src/pedigree/db/queries.py`;
  ran the demo end to end; read `docs/WALKTHROUGH.md` and can narrate the barrier
  and fixpoint]
- [EDIT: any code you wrote or rewrote by hand]
- [EDIT: any decision you overrode or rejected from an agent's proposal]

## 4. Numbers and claims

Every benchmark number in the README and blog is produced by committed scripts
(`make eval` → `evals/results/*.csv` + `evals/REPORT.md` → `scripts/extract_numbers.py`
writes `docs/NUMBERS.md`) and checked by `scripts/check_numbers.py`, which fails if a
number in the README/blog is not in `NUMBERS.md`. The statistician's sign-off is in
`docs/qa/eval-signoff.md` (verdict: SIGNED after the reproduction-path fix).

## 5. Explainability

I can explain the graph model, the queries and the architecture. The plain-language
record is `docs/WALKTHROUGH.md` and `docs/DECISIONS.md` (ADRs, including the
reinstate semantics in ADR-015). `docs/KNOWN_ISSUES.md` lists what is not yet
verified or is known to be limited.

## 6. Tools the product itself does not depend on

The product runs with no model provider: the core service, evals and dogfood harness
use only FalkorDB and Python. LLM settings exist only for the optional demo agent
and are not required for any core feature.
