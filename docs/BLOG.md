# How to un-poison an agent's memory

DRAFT for a human to edit. First person here is proposed copy, not an
attestation that the author personally verified every figure. The longer
working draft remains `docs/BLOG-DRAFT.md`. Numbers are copied from
`docs/NUMBERS.md`. Do not publish this file as a finished post.

An agent reads a page, writes a memory, and later commits code that follows
the memory. If the page was hostile, the question is which beliefs and actions
came from it. A transcript can show that the page was fetched. It cannot show
what else now depends on that fetch.

Vector memory deletes by similarity, so it removes whatever reads like the bad
item. A first-provenance delete leaves beliefs that were also seeded by the
bad episode. Rewinding by time drops unrelated work that happened later. All
three are lineage questions. Lineage is a graph.

Pedigree records that graph in FalkorDB, one graph per tenant. A child points
at its parents with `DERIVED_FROM`, and the parent points back with `FEEDS`,
because `algo.BFS` follows one relationship type. A memory can also point at
an independent source with `CORROBORATED_BY`. Status is stored: `ok`,
`quarantined`, `tainted`, `preserved`, or `revoked`. Revoke marks one source
bad, quarantines the closure, then computes final statuses in topological
order. A parent is bad when it is revoked, tainted, or still quarantined. No
bad parent becomes `ok`. A remaining bad parent with a corroborating source
whose status is `ok` becomes `preserved`. Otherwise it is `tainted`. A parent
that became `preserved` is not bad, which is why the order matters. The gate
then reads those stored labels. It does not re-decide contamination from scratch
on every call.

Lookups anchor on `:Node(id)`, then filter the type label. Anchoring the same
lookup on the type label alone plans as a label scan, and the revoke cost then
grows with the graph instead of with the closure. The measured before-and-after
table lives in `docs/qa/P-010.md`. It is not copied here.

A revoke is four steps, and a crash in the middle is recoverable. One query
marks the root revoked and writes a revocation row whose state is `running`.
A fixpoint then marks the downstream closure `quarantined`, in chunks, and
repeats until nothing healthy remains inside that closure. Anything created
while a parent is already quarantined is born quarantined, which is how a
write that arrives during the cascade stays out of the answer. Python computes
the final statuses, writes them back, and a short verify pass repeats until
no member is still quarantined. If the process dies before that finishes, the
revocation stays `running` and resume completes the same job. A second revoke
of a root that is already revoked does not start another cascade.

The gate is the part a hook can call. It classifies the command, then reads
the nodes the command says it relied on. If that list is empty and the call
names a session, the last reads of that session fill the list. That floor is
intentional: a later command that does not name its inputs is still checked
against what the session already read. A bad parent blocks at medium or high
risk and warns at low risk. The warning becomes a request to re-check only
when the parent list came from that read window. An empty graph, with no
named parents and no session reads, allows the action and says there is no
lineage. Effect and risk are still recorded. Allow, in that case, does not
mean the command was safe.

Source identity is the pair of URI and content hash. Reading the same bytes
again resolves to the same node. A changed hash is a new source, and revoking
the old page does not silently revoke the new one. An agent token cannot mark
a source trusted. A repeat read therefore cannot mint a fresh trusted node
that slips past a revocation.

On generated lineage graphs, the engine's recall is `1.0`, its
over-invalidation is `0.0`, and its explicit preservation-status sensitivity
is `1.0`. A full cascade that ignores support has recall `1.0` as well, and
over-invalidates `0.0493` of unrelated items pooled, `0.2777` in the deepest
cell. A one-hop check recalls `0.1862`. Dropping `1%` of lineage edges in the
capture model leaves `0.012` of contamination undetected. Dropping `10%`
leaves `0.2412`. The conservative read window does not miss in that model, and
it flags extra items at a ratio of `4.4628` to `5.7193` against the truly
affected count. These are generated graphs and a model of missing edges. They
are not a measurement of an installed agent.

The local demo's six-node story is synthetic scenario S1: a page, two
memories, an edit, a commit, and a push that was never executed. None of them
has independent support, so revoking the page taints the other five. The
push's blame path is those six ids. That path is the stored `taint_parent`
chain. It is not Cypher's `shortestPath`, and that chain is not capped by
`max_depth`.

What this does not do: it does not detect a bad source, and it does not stop
prompt injection. Hooks see only what the runtime reports. Bash risk labels
are a heuristic, not a sandbox. A push that already left the machine is listed,
not undone. `preserved` is only as good as the corroboration, and an agent
cannot write the trusted kind of that signal. The Claude hook has localhost
HTTP evidence, not installed-runtime proof. The OpenCode adapter is an opt-in
read-only slice checked by hook replay, not by an installed session. Per-tenant
database users are tested and are not what the shipped service connects with.

Run it from the README: Compose, or `make quickstart` on Linux, or
`make quickstart-windows` when Python is local and the database is Docker.
The walkthrough and the demo script are `docs/WALKTHROUGH.md` and
`docs/DEMO_SCRIPT.md`. The video is not recorded.

AI assistance and the fields a human still has to fill are in
`AI_DISCLOSURE.md`.
