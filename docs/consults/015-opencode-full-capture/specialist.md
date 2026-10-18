# Security response

Approve the observed tools only. Hooks bind pending
calls to callID/path and latch incomplete capture (`pedigree-core.js:410-535`);
preserve those checks across every new branch and bind the pending tool name too.

Post-operation hashes are **observations of current disk state**, not
proof of bytes written by that call: another process can modify the file between
tool completion and hashing. For write, hash the bounded intended `content` before
execution and compare the bounded post-file bytes; mismatch must latch, never claim
an authored artifact. For edit, diff/metadata does not establish the
whole resulting file; either verify a deterministically reconstructed expected result
against the post-file hash, or label the hash as a post-operation observation with
weaker attribution. Do not manufacture exact-write provenance.

Path confinement must reject symlink escapes before execution and recheck after
execution, including replacement of previously safe parent directories. This
detects races but cannot sandbox a filesystem writer; acknowledge that limit.
Do not transmit content, diff, commands, output, or credential-bearing paths.

Bash commands must always carry explicit unknown effect/high risk. A digest loses
classification information; never inherit read/reversible/low defaults or lower risk
based on wrapper parsing. Unknown gate decisions, timeouts and malformed after
metadata deny/latch. Require confirmed success and zero exit before capture; a tool
failure must not produce a successful action.

Required tests: write altered between completion/hash; nested and replaced symlinks;
edit ambiguity; mismatched tool/callID/path; nonzero/missing bash exit; shell wrappers
and redirection; output/content/command privacy; duplicate callbacks; network failure
after mutation; installed execution demonstrating an actual revoked-source denial.
