# Consult 011: strict event validation and error containment

Context: FIX_PROMPT C3 / docs/fixes/P-021.md. P-015 roles implemented, independent
QA PASS and final root/red-team checks running; no new validation edits yet.
Dogfood real HTTP S08/S09 still reproduces conf:5 / artifacts:5 ->500 with Python
exception text; derived_from string iterates characters. Chunked bodies bypass the
Content-Length-only middleware. Strict existing schemas forbid top-level extras,
but events are list[dict[str,Any]] and normalizer silently drops unknown operations.

Question: which smallest compatible shared validation/error boundary rejects all
malformed inputs as typed errors before DB writes, closes chunked body limits, and
avoids leaking request data/credentials through errors or logs across REST/MCP?

Options: A) normalize known aliases, then validate strict canonical event models;
validate raw accepted fields to avoid silently discarding extras; validate complete
batch before writes. B) strict discriminated raw event models for every legacy alias.
Choose exact accepted field/alias contract from actual fixtures/adapters/E3, not guesses.

Constraints: pinned FalkorDB42201 live; installed SDK mcp2.3 actual contract must be
read before configuring body limits. No paidcalls/deploy/push/secrets. All temporary
graphs/registry rows exact-owned and deleted. Do not mutate historical data. Static
parameterized Cypher only in db/queries.py. Phase C consult3of4; bounded review.
P-020 auth/rates remains separate. Keep P-014 quota semantics and P-015 preauthorization.

Need decision on: URI/text control characters (reject rather than silent identity
changes); bounded field/list/item constraints; 422 invalid_argument envelope without
echoing input; unknown events/extras; shared MCP validation vs SDK schema rejection;
pure ASGI actual-byte cap for chunked bodies including MCP mount; unexpected errors
outside _call (auth/registry) and safe correlationIDs. Logs must not print bearer
values even if an injected exception mentions them; full raw request/exception data
is not an acceptable diagnostic contract. Known typed errors can stay actionable.

Context links: src/pedigree/api/{app,schemas,auth}.py; api/routes/{events,engine,gate}.py;
src/pedigree/{adapters,mcp_server}.py; adapters/claude/pedigree_hook.py;
adapters/opencode/pedigree-core.js; tests/integration/test_events.py;
evals/run_e3.py; scripts/dogfood.py S08/S09; tests/security/test_security_F06.py.

Each writes only docs/consults/011-p021-validation/{domain,architect,specialist}.md
<=400words: recommendation, exact evidence, confidence, risks/tests. No src/test edits.
Domain: bounded realDB probe verifying relevant control-character behavior, and
installed SDK actual limit contract. Architect: smallest validation/compatibility plan.
Red-team specialist: malformed/oversized/chunked/error/log/auth fault attack matrix.
