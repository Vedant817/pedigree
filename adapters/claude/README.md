# Claude Code command hook

Set `PEDIGREE_URL` and the tenant `PEDIGREE_TOKEN` in the hook environment.
Merge `settings.example.json` into Claude settings and use the Python executable
available to your shell (`python3` in the example; often `python` on Windows).
The script requires Python 3.11+ and only the standard library.

`prompt` sends a hash-only source and read link. `pre` sends tool/summary and
session id to `/v1/gate` and prints the server's complete `hook` object, including
deny/ask/allow. Risk/effect are classified by the server for normal commands.
Bash commands longer than the API's 300-character summary limit explicitly send
`risk=high` and `effect=unknown`, so a truncated risky suffix cannot lower the
gate's risk classification. `post` hashes regular
files up to 8 MiB for Read/Write/Edit/MultiEdit; Read looks up the exact absolute
`path@sha256` before creating a source. Writes record an Action with that key.
File bodies, edit text, tool responses and raw prompts are never transmitted.
Bash command summaries (up to 300 characters) are transmitted for classification.

Failures produce a generic stderr warning and exit 0; there is no durable spool.
Each HTTP request has a one second timeout and redirects are refused. This is
fail-open capture and gating. A successful protocol unit test does not establish
that Claude installed or executed this configuration.

Limits: Glob/Grep results are not mapped to file reads; shell file I/O, tool
descriptions, memory-glob promotion and web response sources are not captured.
Hashing observes the current complete file, even when Read returned only a
portion; concurrent file changes can race with this observation. Symlinks resolve
to their target. Long Bash command summaries are truncated, with the conservative
risk override described above.
Write ancestry and source hash persistence depend on the `/v1/events` mapping;
the adapter cannot independently prove the server stored these fields/edges.
Synthetic tests are explicitly not recorded Claude runtime payload fixtures.

Source identity remains a capture limitation: artifact lookup currently searches
Memory and Action, not Source. If no artifact matches, each Read creates a new
random Source id. Rereading unchanged file content after revoking its prior Source
can therefore create a fresh trusted file Source and bypass that prior Source's
revocation. Stable source identity and lookup require an F-07/F-08 server/capture
follow-up; this adapter does not claim revocation continuity for those reads.
