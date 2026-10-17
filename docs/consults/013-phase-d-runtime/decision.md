# Decision: separate API/DB, frozen dependencies, owned local runtime

Choose A, unanimously recommended by the three independent reviewers. Build the
API on python:3.12-slim, run as a fixed non-root UID, install runtime dependencies
from a committed uv lock and launch the factory with proxy headers disabled.
Compose owns pinned FalkorDB 4.22.1, bounded module settings and persistent volume;
publish only the API on loopback. Do not couple API shutdown to a detached DB shell.

The optional synthetic demo seeds before API launch and fails startup on failure.
Persist its credential file in a private owner-writable volume, retain identity
and credentials on restart, never log a bearer or rotate implicitly. A local
credential retrieval command is documented for the human. Deployment-admin routes
are disabled in demo mode. This local operator demo is not a public read-only
deployment; optional public deployment is deferred by the prescribed cut order.

Provide a no-Docker quickstart that installs locked dev/localdb extras, discovers
the actual redislite redis-server, fetches/verifies the pinned module and uses
owned process/port/data scope. Refuse foreign/wrong-version listeners and stop only
owned processes. Linux acceptance uses a fresh Python 3.12 container with a glibc
compatible with the published wheel; record the actual distro. Do not claim native
macOS acceptance from wheel metadata. Windows gets a separate Docker DB path.

P-028 commits uv.lock, freezes CI/container/quickstart installs and pins the existing
FalkorDB client. No new Python runtime dependency is chosen. CI uses Python 3.12 and
the pinned DB, running check, history secrets, numbers and bounded perf validation.

Tests first: actual current root UID/deployment setup defect and missing setup
behavior; new tests for demo failure/admin denial/credential retention, owned DB
lifecycle and foreign-listener refusal. Independent QA literally follows README
in an isolated Docker project and fresh Linux clone, checks module42201 and limits,
health, non-root UID, persistence/restart, clean shutdown and no credential output.
Real execution is required; source checks alone do not close runtime acceptance.

Risks: glibc-specific localdb wheels, platform architecture, dependency resolution,
private volume ownership and Windows ACLs. Native macOS and hosted CI remain
unverified until executed. All changes are reversible local setup/configuration;
no public deployment or existing DB migration is authorized here.
