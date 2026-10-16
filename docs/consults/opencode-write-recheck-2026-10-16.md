# OpenCode write-tool shape recheck, 2026-10-16

**BLOCKED before any tool invocation. No write payload fixture was created.**
The earlier genuine read-hook fixture remains unchanged. This attempt establishes
neither write/edit/apply-patch mapping nor E6 runtime coverage.

## Catalog and free-only choice

The installed OpenCode executable was
`C:\Users\vedan\.bun\bin\opencode.exe` (version `1.19.0`, verified during the
earlier same-day read recheck). In a fresh isolated XDG environment, the command
`opencode.exe models opencode --verbose` exited successfully but no longer
listed `opencode/deepseek-v4.1-flash-free`. That missing identifier was not used.

The catalog did list `opencode/mimo-v2.6-flash-free` as active, supporting tool
calls, with input, output, cache-read and cache-write costs all zero. The one
session therefore selected that genuinely catalog-listed free alternative for
its primary agent, main model and small model. Only the `opencode` provider was
enabled; no paid fallback or second model session was attempted.

## Isolation and exact request

A fresh `pedigree-opencode-write-recheck-*` temporary project outside this
repository was initialized as its own Git repository. Separate XDG config,
data, cache and state paths and `OPENCODE_CONFIG_DIR` isolated runtime state.
Credential/provider/T3 variables were removed from the child environment; no
credential files or private project files were copied. Sharing and auto-update
were disabled. No Claude call or Pedigree service/database operation was made.

The primary agent exposed only the native `write` tool. The observation plugin
would log genuine before/after input/output and reject anything except one
write of `dummy-result.txt` inside that temporary project, containing exactly
`F08_SYNTHETIC_WRITE_OK` followed by one newline. It also recorded the first
provider retry/error separately so the controller could stop immediately.

```text
opencode.exe run --agent spike --model opencode/mimo-v2.6-flash-free --format json --title "Synthetic F08 write recheck 2026-10-16" "Use the native write tool exactly once to create dummy-result.txt in the current project directory with content exactly F08_SYNTHETIC_WRITE_OK followed by one newline. Do not use shell, read, edit, apply_patch, or any other tool."
```

## Bounded observed failure

The one session had a 60-second wall limit and was stopped at its first provider
error, after 28.41 seconds. Bounded raw provider fields, omitting transport
headers and opaque request IDs:

```json
{
  "name": "APIError",
  "statusCode": 403,
  "isRetryable": false,
  "message": "OpenCode's free tier can only be used from within OpenCode. Download it at https://opencode.ai and keep building.",
  "responseBody": "{\"type\":\"error\",\"error\":{\"type\":\"FreeTierError\",\"message\":\"OpenCode's free tier can only be used from within OpenCode. Download it at https://opencode.ai and keep building.\"}}"
}
```

This is the provider's actual rejection while using the installed OpenCode CLI;
its cause was not established. It is not evidence of a missing subscription or
a reason to use paid credentials. No workaround or retry was attempted.

There were zero `tool.execute.before`/`tool.execute.after` events and no
`dummy-result.txt`. Stdout contained the CLI's JSON provider-error event; stderr
was empty. The controller terminated only
its own session process tree; exit code after termination was 1. A subsequent
process check found no OpenCode process with this synthetic session title.

The native write payload remains unverified. The read-only genuine fixture does
not justify inventing the write contract, and this blocked attempt contributes
no E6 case-study or benign-friction samples.
