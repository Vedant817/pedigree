# F-08 independent adversarial review (OpenCode read-only capture slice)

Date: 2026-10-16. Scope: the declared F-08 slice — opt-in read-only OpenCode
adapter, `adapters/opencode/**` (ADR-009, `docs/features/F-08-opencode.md`) — at
commit `c14d7fb` (pre-fix; since amended to `8dd6509`, see QA F08-QA-1).

**Verdict: PASS after repair for the declared hook-replay scope.** Seven
adversarial findings: three real defects in the adapter's path/identity layer
(one High), three disclosure-level bounded/inherent limits, one pre-existing
server-side issue out of scope. All three defects are fixed and covered by
permanent regressions (`tests/security/test_security_F08.py`, `paths.test.js`,
`tests/integration/test_opencode_plugin.py`); the disclosures are in the adapter
README known-limits section.

Authorship note: the adversarial experiments and raw evidence were produced in a
red-team session (scratch harnesses under `scratch/redteam-f08/`, gitignored);
this report was compiled by the orchestrator, which independently re-ran every
finding's reproduction before and after the fixes. The independent QA re-run of
the fixes is recorded separately (see the addendum in `docs/qa/F-08.md`).

## Environment and method

- Windows 11, Node v24.13.1, Python 3.12.15, FalkorDB v4.22.1 (module 42201)
  via Docker. No OpenCode model sessions were started; all experiments drive the
  real plugin entry/core (`pedigree.js`/`pedigree-core.js`), the real replay
  driver (`tests/driver.js`), real local HTTP sockets, and for the live set the
  real FastAPI app + real FalkorDB through a fresh session-owned tenant graph.
- Pre-fix reproduction: `scratch/redteam-f08/legacy/pedigree-core.js` is pinned
  from `c14d7fb`; `*-legacy.mjs` harness copies import it. Post-fix: the same
  harnesses against the working tree (`8dd6509`).
- Raw outputs are local (`scratch/redteam-f08/*.out.json`); the excerpts below
  are verbatim from those files.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| F08-RT-1 | Windows alternate data streams bypass credential exclusion and capture: `id_rsa::$DATA`, `.env::$DATA`, … resolved to an in-root rel path that `isCredentialPath` does not match, and the OS read returned the real credential bytes. | **High** | **Fixed** — win32 grammar denial (`path_stream`) before resolution; Node regressions + `test_security_F08.py`. |
| F08-RT-2 | Drive-relative form `C:file` opens `file` in the *process current directory of drive C* (not the project) while the adapter records `<project>/file` — wrong-file provenance. | Medium | **Fixed** — `C:file` denied (`path_stream`); win32 regressions. |
| F08-RT-3 | `fs.realpathSync` preserves the caller's case, so `CASE.TXT` and `case.txt` minted two Source identities (split uri and digest) for one file. | Medium | **Fixed** — native resolver (`fs.realpathSync.native`) canonicalizes existing paths; live pre/post evidence below, plus a live integration test. |
| F08-RT-4 | Latch-ring forgetting: after >64 tracked-session evictions + 256 ring entries of churn, an incomplete (latched) session that reappears is treated as new and allowed. | Low (disclosure) | **Disclosed** — bounded memory is deliberate; adapter README known-limits. Not a correctness fix: an unbounded latch set would be a memory DoS. |
| F08-RT-5 | Gate read-window eviction: the gate consults the session's last `pedigree_read_window` (default 50) distinct reads; a revoked source evicted by 50 newer reads is no longer consulted, and one read was observed allowed after churn. | Low (disclosure) | **Disclosed + watchdog** — server semantics (not adapter code); documented in adapter README; strict-xfail watchdog in `test_security_F08.py` flips if semantics change. |
| F08-RT-6 | TOCTOU: the path is validated in the before hook; a symlink swapped before the runtime's read yields a capture whose uri/rel is the in-root link while the digest is over the bytes the runtime actually read (display view). | Low (inherent) | **Disclosed** — the guarantee is "digest over the observed display view", never "bytes on disk at identity path"; README states this. |
| F08-RT-7 | `/v1/events` does not enforce `node_cap` (a capped tenant can grow the graph through event batches). | Pre-existing | Out of F-08 scope — already tracked as **P-014** in `AUDIT.md` (quota bypass via `/v1/events`; fix: shared `enforce_quota` in the ingest engine). The adapter sends events through the documented channel; no new exposure. |

### F08-RT-1 raw evidence (e1c)

Pre-fix (`e1c-legacy.out.json`, harness `e1c-ads-cred-legacy.mjs`):

```json
{"candidate": ".env::$DATA",  "rel": ".env::$DATA",  "isCredential": false, "read": "CONTENT-OF-.env\n"}
{"candidate": "id_rsa::$DATA","rel": "id_rsa::$DATA","isCredential": false, "read": "CONTENT-OF-id_rsa\n"}
{"candidate": "cert.pem::$DATA", "rel": "cert.pem::$DATA", "isCredential": false, "read": "CONTENT-OF-cert.pem\n"}
```

Post-fix (`e1c-fixed.out.json`): every stream candidate resolves to
`{"denied": "path_stream"}`, so the before hook denies before the read executes
(and before any network call). Device names (`CON`, `NUL`, `AUX`, `COM1`,
`LPT1`) were probed and are `ENOENT` inside the root — no bypass there.

### F08-RT-2 raw evidence (e1b)

Pre-fix (`e1b-legacy.out.json`; cwd set to a directory on the same drive):

```json
"cwdTest": {
  "osRead": "CWD-CONTENT\n",
  "adapterResolved": {"rel": "drivefile.txt"},
  "adapterWouldRecord": "<project>\\drivefile.txt"
}
```

The OS opened the cwd file; the adapter would have recorded `<project>/drivefile.txt`.
Post-fix: `"adapterResolved": {"denied": "path_stream"}`.

### F08-RT-3 raw evidence (e1b + live e7)

Pre-fix single process:

```json
"realpathCase": {
  "realpathSync": "<project>\\DUMMY.TXT",
  "realpathSync.native": "<project>\\dummy.txt",
  "ondisk": ["dummy.txt"]
}
```

Live pre-fix (`e7d.out.json`, real API + FalkorDB): two Sources for one file —
`case.txt#L1-L1` (digest `1ce962…`) and `CASE.TXT#L1-L1` (digest `e7bb25…`).
Live post-fix (`e7-postfix.out.json`): one Source — `case.txt#L1-L1` only.

### F08-RT-4 raw evidence (e3)

`e3-fixed.out.json` (code unchanged by the fix):

```json
"eviction": {
  "churn": 325, "sizeAfterChurn": 64,
  "revived": {"decision": "allow"},
  "victimAfterRevive": {"incomplete": null, "pending": 1, "...": "..."}
}
```

The victim session was latched (`capture_failed`), then 325 other sessions were
churned (> 64 tracked + 256 remembered-evictions), then the victim session ID
was used again and was allowed as a new session.

### F08-RT-5 raw evidence (live e7, T2)

Post-fix (`e7-postfix.out.json`; identical pre-fix):

```json
"T2_window_overflow": {
  "reads_before": ["allow", "allow", "allow"],
  "victim_row": [["src_oc_7e437d852efaa474", "ok"]],
  "read_after_revoke_and_churn": {"decision": "allow"},
  "captured_after_churn": {"captured": true},
  "session_reads_after_churn_count": 53,
  "revoked_still_in_window": true
}
```

(`revoked_still_in_window` is the harness's check over the full READ edge set,
not the gate's bounded window; the authoritative observation is the `allow`
after churn. Immediately after revoking with no churn, the same session is
denied `gate_reverify` — see T1/T2-contrast in the same run.)

### F08-RT-6 raw evidence (e4)

`e4-fixed.out.json` (identical pre/post fix):

```json
"toctouSwap": {
  "swapPossible": true,
  "before": {"decision": "allow"},
  "after": {"captured": true},
  "captured": {"uri": "readview:v1/p_16f8…/safe.txt#L1-L1", "content_hash": "8a5125…"},
  "note": "uri/path says the in-root link target, digest is over the outside bytes"
}
```

## Attack inventory (behaved as designed; no findings)

| Area | Probes | Result |
|---|---|---|
| Transport trust (e2, real sockets) | redirect responses, plaintext remote base, malformed/garbage JSON, oversized + lying content-length, chunked slow-loris, timeout mid-body, 401/500 | All deny with fixed sanitized messages; no retry; body of a 4 MiB display stays 369 bytes; no canary on the wire. |
| Payload spoofing (e4) | null/number/array/empty inputs; `tool` non-string/empty; spoofed `integrity`/`kind`/`tenant`/`risk` fields in args/output; `toString` objects as filePath | All denied `malformed`/`unsupported` with zero network; spoofed trust fields never reach the wire. |
| Identity (e3/e4) | huge session ids (hashed + bounded key), hostile call ids across sessions, callID reuse after ack, session-id collision `ped:abc` vs `ped:abcd`, unicode/hostile filenames (`x' MATCH (n) DETACH DELETE n --.txt`, `ünïcødé-文档.txt`) | Namespaced keys stay inside the server grammar; per-session scoping correct; hostile names captured literally with no query effect (engine-side proof in QA live probe 8). |
| Privacy (e6, genuine entry + driver subprocess) | canaries in file bytes, tool output, preview, title, args, absolute paths, operator token; stdin/stdout/stderr capture | No canary in stdout (JSON report), stderr (fixed sanitized lines only), or request bodies at any stage. |
| Denial-order (e3/e4) | latch cannot be cleared by a later allow; unsupported tools denied with zero network; gate outage does not latch but denies; malformed display latches fail-closed | All as documented; no request amplification (one attempt per stage). |
| Live API (e7, real FalkorDB) | tenant isolation of identical captures; revoke scope per tenant; hostile payload fields; window churn (above); case variants (above) | Isolation and revoke scope correct; no cross-tenant bleed; hostile fields never persisted. |

## Residual limits (not defects, must not be over-read)

- Installed-runtime acceptance of the plugin file remains unverified (hook
  replay only; no new model sessions per ADR-009).
- The disclosures F08-RT-4/5/6 are limits of bounded memory, the server's
  influence window, and the observed-display trust model respectively.
- 8.3 short names are not generated on the test volume and device names are
  `ENOENT` inside a root — no third path-grammar bypass was found, but this is
  not an exhaustive proof of the Windows path grammar.
