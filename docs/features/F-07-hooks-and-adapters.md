# F-07 - Claude/OpenCode hooks + /v1/events + cross-session artifact links

Status: qa | Tests: `tests/integration/test_events.py` | QA: pending

## Behaviour
- `src/pedigree/adapters.py` normalizes Claude/OpenCode/generic runtime events into
Courd operation specs: source/memory/action/session/session_read. Unsupported event kinds are
ignored rather than crashing ingest.
- `POST /v1/events` executes those operations against the authenticated tenant graph.
- Added `/v1/artifacts/lookup?key=...` and `/v1/invariants` convenience endpoints.
- `pytest tests/integration/test_events.py` -> 1 passed.<|end|>