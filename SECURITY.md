# Security policy and trust model

Pedigree records agent-reported or runtime-observed lineage, propagates revocations,
and evaluates declared dependencies before an action. It is not an operating-system
sandbox or proof that an agent reported every influence. This policy covers the
Python service, REST/MCP interfaces, browser workspace and shipped capture adapters.
It states required boundaries and known limitations; it does not suppress findings.

## Principals and assets

Protect tenant graph data, credential digests, attestation authority, lifecycle
state, gate decisions and availability. Treat all request bodies, tool arguments,
claimed runtime identities, source locations and graph IDs as attacker-controlled.

- An **agent bearer** permits tenant ingest, reads, agent-authored corroboration
  and gate checks. It cannot revoke/reinstate or claim trusted source integrity or
  human/scanner attestation. Legacy tenant bearers retain agent authority only.
- A **tenant operator bearer** intentionally adds those privileged operations.
  Explicit operator REST/MCP calls are supported; shipped MCP defaults and hooks
  require agent credentials. Giving an operator bearer to an agent grants its powers.
- The **deployment administrator** provisions tenants and performs deployment-wide
  recovery. Its header does not elevate an agent bearer on tenant operations.
- The service process and direct database credentials are privileged. Per-tenant
  database ACL mechanisms have been tested but are not wired into service connections.
  API isolation therefore does not protect against a compromised database principal.

New credentials are delivered once and only digests persist in the registry. Prefixes
are hints, not authority. Rotation/status checks must use current stored authority.
Credential files are private local material, not configuration to commit or expose.
The UI retains a supplied bearer in page memory rather than browser persistence.

## Threats and required boundaries

**Prompt-injected agent with a valid agent bearer.** Authorization must precede
mutations. An agent plus a valid deployment-admin header must still be unable to
mint trusted attestations or invoke operator actions. Full event batches reject
forbidden claims before writing. Agent corroboration may produce descriptive
`preserved` lifecycle state; the gate separately requires human/scanner attestation
to treat preservation as trusted containment. The status label is not verification.

**Malicious tenant or unauthenticated network caller.** Derive tenant and role from
the matching stored credential, never a body, query field or tool tenant argument.
Scope queries to the resolved graph. Cross-tenant IDs must not expose or mutate
another tenant. Missing lineage is not evidence that a dependency is safe. Keep
static parameterized Cypher, strict bounded inputs and actual-byte HTTP limits,
including chunked REST/MCP bodies. Structurally malformed batches must not partially write.
Unexpected errors and diagnostics must not reflect raw inputs or secret-bearing
exception messages/causes. Correlation IDs are server-generated.

**Spoofed hook or runtime observation.** An unauthenticated observation must not
write. Possession of an agent bearer can fabricate agent evidence; a runtime name,
URI or content hash is not an attestation. Source deduplication links identities,
but does not independently fetch or verify the artifact. A caller can omit lineage.
The gate evaluates the supplied graph/window and configured classifier, not every
possible influence or actual future external effect.

**Resource abuse and concurrent writers.** Public creators must share request-wide
quota admission and count physical growth, including sessions and revocation ledgers.
Quota overflow rejects the batch before mutation. Other engine/DB failures can
retain earlier sequential event writes; ingestion is not a transaction. Rate limits
must count each admitted operation once and keep read/write budgets separate.
Authentication backoff must use a trustworthy peer and bounded state. Per-instance
limits are not distributed enforcement and reset or multiply across restarts/workers.

## Operational assumptions and remaining limits

- Quota coordination requires one stable Redis/Falkor primary, cooperating public
  writers and coordination keys protected from eviction/loss. Its mutex has no expiry.
  Crashes or ambiguous writes can block a tenant until writers stop and database work
  is confirmed quiescent, then an operator removes the exact key. There is no failover
  fencing guarantee. A full graph can reject a new revocation/reinstatement ledger.
- Direct trusted engine callers can bypass public quota/rate policy. Protect service
  and DB credentials and keep the database unreachable from untrusted clients. The
  current local compose port mappings are not a verified production network boundary.
  TLS, proxy trust and hosting configuration need deployment-specific verification.
- Claude hook network/malformed-payload failures remain fail-open. Local operator-token
  configuration is denied, but hooks are not a sandbox or comprehensive capture system.
  Shell risk classification is heuristic; unhooked I/O and omitted dependencies remain
  outside its observations. External effects already performed are reported, not undone.
- The OpenCode adapter is an opt-in read-only slice. Hook replay against a live local
  service is verified; installed-session acceptance, writes/edit/shell capture and
  real-session coverage/friction are not established. Claude installed-runtime proof
  also remains open.
- MCP stdio parser containment depends on isolated, checked installed SDK runner
  plumbing. The HTTP body cap does not bound the SDK's stdin-line allocation.
- Application-specific metrics and structured trace coverage remain incomplete.
  Local tests, synthetic evaluation and container checks do not establish production
  readiness, hosted isolation or physical/installed agent behavior.

See [known issues](docs/KNOWN_ISSUES.md), [quota contract](docs/fixes/P-014.md),
[role contract](docs/fixes/P-015.md) and [input/error contract](docs/fixes/P-021.md).
Auth/rate evidence: [independent QA](docs/qa/P-020.md) and
[red-team](docs/qa/redteam-P-020.md) cover live indexed authority, shared request
budgets and peer backoff. These local passes do not establish distributed limits.
Evidence includes [admin red-team](docs/qa/redteam-P-013.md),
[role red-team](docs/qa/redteam-P-015.md), [MCP red-team](docs/qa/redteam-P-016.md)
and [validation red-team](docs/qa/redteam-P-021.md). Reports state local scope and limits.

## Reporting and severity

Report reachable cross-tenant disclosure/mutation, agent-to-operator escalation,
unjustified gate trust, secret reflection and quota/rate bypasses with exact inputs,
observed outputs and affected revision. Distinguish public capabilities from access
requiring service/DB compromise. Denial of service and misleading trust state are
reportable; known limitations are not blanket exclusions. No severity is reduced
merely because a test suite passes or the data is synthetic.

**Private disclosure contact: TODO — repository owner must supply a monitored
security address before public release.** No address is claimed to be monitored.
Do not post credentials, personal data or an unredacted private-data exploit in a
public issue. The owner must establish a private contact channel for such reports.
