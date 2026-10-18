# OpenCode native capture: builder verification

Date: 2026-10-18. Independent correctness/security QA is pending. No push, hosted
CI, preview deployment or TestSprite execution is claimed by this report.

## Acceptance and environment

Consult015 decision governs: native read/write/edit/bash only; matched hooks;
unknown/high mutations; intended write/edit digest comparison; credential and
symlink confinement; no bodies/commands/output transmitted to Pedigree; missing
or unsuccessful mutation capture latches rather than reporting success.

Started from release baseline `2947c30`. Imported only the authorized OpenCode
diff and three explicit new files from the preserved checkout at `04c8acf`.
Its handoff was not copied. The original checkout and Claude spools were not
edited. The existing Python virtual environment was used with this checkout's
`src` on `PYTHONPATH`.

Dedicated DB command:

```powershell
docker run -d --name pedigree-opencode-db-20261018 -p 127.0.0.1:6387:6379 falkordb/falkordb:v4.22.1
```

Real integration fixtures assert module version `42201`. Installed acceptance
used a fresh local API on `127.0.0.1:8117`, pointing only to this database. The API
process was terminated after each probe. No existing database was reused.
Integration test servers additionally bind fixture-owned ephemeral loopback
ports against the same dedicated DB.

## Test-first defects and focused results

`node --test adapters/opencode/tests/native-tools.test.js` initially returned
10 pass / 1 fail: replacing an originally safe symlink while reporting its old
canonical target incorrectly recorded an action (`1 !== 0`). The fix revalidates
the original requested path as well as metadata before observing the artifact.

Installed execution from a subdirectory exposed relative-path disagreement:
OpenCode uses its runtime directory, while the adapter used the worktree root.
`node --test --test-name-pattern='runtime directory' adapters/opencode/tests/native-tools.test.js`
failed (`undefined` versus `{captured:true}`) before the fix. Runtime-directory
resolution now preserves canonical worktree identity and confinement.

A missing edit target also reproduced an unsanitized `ENOENT` before the gate.
Its regression expected `malformed` and failed before the filesystem-error
wrapper was added. It now denies with zero network requests and no absolute path
or OS diagnostic in the error.

Final focused commands, with `FALKOR_PORT=6387` and this checkout's `src` on
`PYTHONPATH`:

```text
node --test adapters/opencode/tests/*.test.js
tests 55; pass 55; fail 0; skipped 0 (exit 0)

python -m pytest -q tests/unit/test_opencode_adapter_suite.py tests/integration/test_opencode_plugin.py tests/security/test_security_F08.py
6 passed, 1 xfailed in 6.08s (exit 0; before the runtime-directory regression was added)

python -m pytest -q tests/security/test_p021_review.py::test_review_actual_stdio_sdk_does_not_reflect_malformed_arguments tests/unit/test_opencode_adapter_suite.py tests/integration/test_opencode_plugin.py tests/security/test_security_F08.py
7 passed, 1 xfailed in 8.22s (exit 0; final implementation)
```

Cases include: nonzero/missing/string exits; output mismatch/truncation;
call/tool/argument/path mismatches; missing mutation after-hook; duplicate hooks;
ambiguous old strings and unexpected edit poststate; write digest mismatch;
escaping/replaced symlink parents; credential paths and Windows normalized
aliases/device names; oversized content/artifact keys; failed capture delivery;
denied execution spies and raw-value privacy canaries. Live graph replay proves
artifact hashes, source/action dependency edges, untrusted shell-output identity,
tenant isolation and high-risk denial after untrusted influence.

## Installed execution, separate from replay

`opencode --version` returned `1.19.3`; selected model `opencode/beam-free`.
Authenticated OpenCode executed the actual plugin entry. No Claude session was
used. Explicit plugin registration kept the helper module outside autoload.
Unrelated global MCP registrations were disabled in probe-local configuration
after an initial provider rejection: `Invalid value for 'tools': maximum number
of items is 128.` That rejected attempt provides no tool-execution proof.

The ignored local runner `scratch/opencode-native/runtime.py` spawned the API,
provisioned a synthetic tenant without printing its credentials, copied this
checkout's adapter, and invoked `opencode run --dir <probe-project> -m
opencode/beam-free --format json <synthetic-prompt>`. It saved local structural
hook records and queried the dedicated graph. Prompts requested exactly one tool
per new session: write `sample.txt` containing `owned before` plus a newline;
edit the unique `before` to `after`; Bash `echo owned`; then read `sample.txt`.

Final installed results (each CLI exit 0):

```text
write: completed; paired hooks; captured true; persisted Action unknown/high
edit:  completed; paired hooks; captured true; persisted Action unknown/high
bash:  completed; paired hooks; exit 0; captured true; persisted Action unknown/high
read:  completed; paired hooks; captured true; persisted untrusted Source
operator revoke: HTTP 200
resumed read: same session ID; before hook gate_reverify; no after hook
Pedigree API content/command canary matches: 0
```

Write artifact digest:
`48d0dff6005ffc3bb948dbeefe280b5498527327d0bfe791b4a26d6010a9347b`.
Edit artifact digest and independently read final 12-byte file digest:
`23741f4e35db0a39fdceb6e17a66c5278efd282da9606b38dd3c3c12761e6a52`.
The installed Bash output Source was independently matched to the runtime output
digest `c33ce4170e5377b81606729c2bac70868baf6d1344fff23fbc82b17915e3ae75`
and persisted as `tool_output`, `untrusted`, `ok`. The captured read Source
persisted as `file`, `untrusted`, `revoked` after the operator request.
Read revocation used the operator bearer only in the harness; the plugin received
only the agent bearer. Continuation used `--session` in a new CLI process, so
this proves persisted session gating, not preservation of in-memory latch state
across restarts. The final file operations and Bash used separate clean sessions;
their installed test does not establish a continuous cross-tool influence chain.
The real-DB replay independently tests that chain using the existing read window.

An earlier installed Bash `printf owned` failed under this Windows PowerShell
runtime with integer exit 1. It emitted no successful Action; the plugin logged
`capture incomplete (invalid_native_result)`. Bash success required the supported
host command `echo owned`. Runtime tool status `completed` alone did not imply
shell success. This was an actual runtime failure, not a manufactured assertion.

The observer retained only tool/argument/metadata keys, numeric exits, capture
results and privacy booleans for Pedigree requests. Provider model requests are
outside that privacy claim. Raw synthetic runtime logs stay ignored locally;
credentials are never part of tracked evidence.

## Full gate and limits

First `make check` run: Ruff passed; `1 failed, 910 passed, 1 skipped,
6 deselected, 1 xfailed in 183.88s`. Failure:
`test_review_actual_stdio_sdk_does_not_reflect_malformed_arguments` raised
`StopIteration` because the stdio child produced no reply with ID 2. The focused
rerun above passed without changes to stdio code/tests. Secret/numbers/README
checks were not reached by that failed invocation.

Final full gate command: `make check PY=<existing-venv-python>`, with
`FALKOR_PORT=6387` and this checkout's `src` on `PYTHONPATH`. Actual output:

```text
All checks passed!
911 passed, 1 skipped, 6 deselected, 1 xfailed in 254.48s (0:04:14)
[secret-scan] PASS: no credential shapes found in tracked files
[check-numbers] PASS: 4 file(s) checked against 70 allowed values
[check-readme] PASS: 11 headings, docs/*.md links, numbers
```

Exit 0. The installed acceptance runner was rerun on the final implementation:
write/edit/bash completed and persisted, revoked read denied, API canary matches
zero. Final Node suite: 55 passed, zero failed/skipped. `git diff --check` passed.

No traversal/revoke/gate implementation changed; `make check-perf` was not run.
File-path confinement applies to native read/write/edit. Arbitrary Bash is not a
filesystem sandbox and can access paths outside the project; its effects are
unknown/high and its observed output enters the untrusted read window.
Unsupported tools/options, arbitrary shell filesystem provenance, approval UX,
cross-session artifact links, durable restart receipts/latches, bounded session
eviction and bounded read-window influence remain limitations. Hash equality
does not prove exclusive authorship or prevent filesystem TOCTOU. Cross-platform
installed acceptance beyond this Windows runtime is unverified. This is builder
evidence, not an independent QA or release approval.
