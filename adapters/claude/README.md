# Claude Code command hook

Set `PEDIGREE_URL` and the tenant **agent** `PEDIGREE_TOKEN` (`ped_a_…`) in the hook
environment. Legacy tenant tokens remain agent credentials. Never configure an
operator bearer (`ped_o_…`): the hook rejects it locally before reading input or
sending requests, exits 2, and emits a deny decision for `pre`.
Merge `settings.example.json` into Claude settings and use the Python executable
available to your shell (`python3` in the example; often `python` on Windows).
The script requires Python 3.11+ and only the standard library.

`prompt` sends a hash-only source and read link. `pre` sends tool/summary and
session id to `/v1/gate` and prints the server's complete `hook` object, including
deny/ask/allow. Risk/effect are classified by the server for normal commands.
Bash commands longer than the API's 300-character summary limit explicitly send
`risk=high` and `effect=unknown`, so a truncated risky suffix cannot lower the
gate's risk classification. `post` hashes regular
files up to 8 MiB for Read/Write/Edit/MultiEdit. Read persists the exact absolute
`path@sha256`; the service resolves its artifact producer during delivery, before
creating a source. Writes record an Action with that key.
File bodies, edit text, tool responses and raw prompts are never transmitted.
Bash command summaries (up to 300 characters) are transmitted for classification
after URL userinfo and credential header or flag values are redacted.

Capture envelopes are persisted before network access in a private SQLite outbox
under `~/.pedigree/spool`, configurable with `PEDIGREE_SPOOL_DIR`. Each endpoint and
credential fingerprint has its own queue; bearer credentials are never written to
the queue. Keep this directory on durable local storage outside tracked source.
Its files inherit the current Windows account's ACL; POSIX files are created mode
0600. Capture retains paths, URLs, hashes and action metadata; protect these files
as user data. Durable Bash actions retain only the tool name plus conservative
high risk/unknown effect, so arbitrary shell arguments cannot leak into the spool.
Pre-tool gate requests still send redacted summaries directly for classification.

The queue holds at most 1000 envelopes or 8 MiB of payload per namespace. SQLite's
data file is capped at 4096 pages (normally 16 MiB), with temporary journal overhead.
Full, corrupt or unwritable storage reports failure; queued evidence is never
silently evicted. A separate process lock serializes replay while allowing enqueue
during network waits. Every request times out after one second; redirects are refused.
Automatic hooks drain at most three envelopes to stay below the shipped ten-second
runtime hook timeout; a larger backlog denies the gate. To drain up to 20 manually:

```sh
python adapters/claude/pedigree_hook.py replay
```

Repeat if the command reports remaining work. Use the original endpoint and agent
credential to drain an old queue after account switching or rotation. Server delivery
receipts provide retry identity, including after an acknowledgement is lost. The
service must support `delivery_id`; an older service cannot acknowledge durable
delivery, so the queue remains intact until upgrade. An ambiguous DB write can
retain the existing tenant quota mutex; only an operator who has stopped all writers
may perform its documented recovery. Do not delete receipts or mutexes to retry.

`pre` first drains pending capture, then obtains a fresh gate decision. Pending
capture, connectivity failure, malformed input or unavailable storage emits an
actionable **deny** decision. Gate decisions are never queued or reused. Post/prompt
failures return nonzero and warn; evidence already queued remains available for
replay. Operator-token configuration is rejected as described above. These protocol
and live-service tests do not establish installed Claude runtime execution.

`WebFetch` records `Source(kind=web, integrity=untrusted)` for an http(s) URL
with no userinfo, plus a session READ. `WebSearch` records the same kind of
source with uri `websearch:sha256:<digest>`; the query text is not sent.
`Bash` commands `cat`, `head`, `curl`, and `wget` record READ edges for path
or http(s) URL operands. Flags that take a value are recognised per command, so
`cat -n file` still records that file, and `sudo -u user cat file` records the
file rather than the session window. `env`, `command`, `exec`, and `bash -c`
are unwrapped the same way. Compound commands are split on `&&`, `||`, `;`, `|`,
`&`, and newlines outside quotes, so a quoted query string stays one URL. A
segment that cannot be parsed is not recorded as a read. A `curl`/`wget` write
(`-X` or `--request` other than GET/HEAD, `-d`, `-F`, `--json`, `-T`, and the
wget post or body flags) is an action and not a read. When a bash command does
record reads, that action's `relied_on` is those nodes only, so an earlier
unrelated read in the session is not a parent of this command. The pre-tool
gate still sends the session id and no explicit `relied_on`, so ADR-007's
read-window floor still applies to `git push` and any other command that does
not name its own inputs. `ssh`, `scp`, and `sudo` are classified as command
tokens, including `env ssh`, `bash -c "ssh …"`, and `ssh.exe`.
`cat ~/.ssh/config` is not an ssh invocation.

Limits: Glob/Grep results are not mapped to file reads. Shell writes, tool
descriptions, and memory-glob promotion are not captured. Page and search
bodies are not fetched or stored. This adapter is validated on synthetic
payloads only (`tests/fixtures/claude/`); installed Claude Code sessions are
not recorded here.
Hashing observes the current complete file, even when Read returned only a
portion; concurrent file changes can race with this observation. Symlinks resolve
to their target. Long Bash command summaries are truncated, with the conservative
risk override described above.
Write ancestry and source hash persistence depend on the `/v1/events` mapping;
the adapter cannot independently prove the server stored these fields/edges.
Synthetic tests are explicitly not recorded Claude runtime payload fixtures.

Artifact lookup searches Memory and Action, not Source. A Read that misses that
lookup still posts `uri` and `content_hash`. The server merges that pair onto the
existing Source and rewrites later ids in the same batch to it, so a reread of
the same bytes does not fork a second node. An agent token cannot set
`integrity=trusted`. A changed hash is a new Source, which is the ADR-008 rule.
