# OpenCode S-B payload spike (F-08 preflight)

Date: 2026-10-15, Asia/Kolkata. **BLOCKED by free-provider quota; no real
`tool.execute.after` shape was captured.** Do not treat the companion JSON as a
successful tool fixture. Its `tool_execute_after` and `tool_execute_before` are
explicitly null; it contains real sanitized session events only.

Read docs/01 section 8.2, docs/04 section 11, docs/05 spike S-B. Verified current
[official plugin documentation](https://opencode.ai/docs/plugins/) and
[configuration documentation](https://opencode.ai/docs/config/). The installed
binary loaded the temporary project plugin and emitted genuine session events.

## Preflight

Commands (PowerShell):

```powershell
& 'C:\Users\vedan\.bun\bin\opencode.exe' --version
& 'C:\Users\vedan\.bun\bin\opencode.exe' run --help
& 'C:\Users\vedan\.bun\bin\opencode.exe' models opencode
& 'C:\Users\vedan\.bun\bin\opencode.exe' models opencode --verbose | Select-String -Pattern 'deepseek-v4.1-flash-free' -Context 0,28
```

Observed version: `1.19.0`. Catalog includes
`opencode/deepseek-v4.1-flash-free`, status `active`, tool calls supported;
input/output/cache-read/cache-write cost fields are all `0`. Catalog availability
does not imply available free quota. No credential/config secrets were printed.

## Isolation and execution

Created a new temp directory named `pedigree-opencode-spike-*` outside this
repository, with its own `project/.git` boundary, `dummy.txt`, `opencode.json`
and `.opencode/plugins/capture.js`. No private project files were copied.
`dummy.txt` was marked read-only and contains exactly:

```text
Synthetic Pedigree OpenCode spike. Marker: F08_DUMMY_READ_OK.
```

The child process received separate temporary `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_CACHE_HOME`, `XDG_STATE_HOME` and `OPENCODE_CONFIG_DIR`. Inherited variables
whose names contain API_KEY, AUTH_TOKEN, ACCESS_TOKEN, OPENCODE, PEDIGREE,
ANTHROPIC, OPENAI, GEMINI, GROQ or T3_ were removed from that child environment.
No user HOME variable was changed. Sharing and auto-update were disabled.
An explicit primary agent, main model and small model all selected the same free
model; enabled providers were restricted to `opencode`. Permissions defaulted to
deny and allowed only the dummy file read. No `--auto`, `--share`, attachment,
paid fallback, MCP server or remote write was requested.

Temporary plugin implementation (logging only to local `capture.jsonl`):

```javascript
import { appendFileSync } from "node:fs";
import { join, resolve } from "node:path";
export const Capture = async ({ directory }) => {
  const log = (event) => appendFileSync(join(directory, "capture.jsonl"), JSON.stringify(event) + "\n");
  log({ hook: "plugin.initialized", directory });
  return {
    "tool.execute.before": async (input, output) => {
      log({ hook: "tool.execute.before", input, output });
      if (input.tool !== "read" || resolve(output.args.filePath) !== resolve(directory, "dummy.txt"))
        throw new Error("Synthetic spike permits dummy.txt read only");
    },
    "tool.execute.after": async (input, output) => log({ hook: "tool.execute.after", input, output }),
    event: async ({ event }) => {
      if (event.type.startsWith("session.")) log({ hook: "event", event });
    }
  };
};
```

The one session was launched with Python `subprocess.run`, `cwd` set to that
isolated project, captured stdout/stderr, and a 70-second wall timeout. Exact CLI:

```text
C:\Users\vedan\.bun\bin\opencode.exe run --agent spike --model opencode/deepseek-v4.1-flash-free --format json --title "Synthetic F08 shape spike" "Read dummy.txt with the read tool exactly once and report the marker. Do not use any other tool."
```

## Measured result

The local plugin initialized. Runtime emitted `session.created`,
`session.updated`, `session.status`, `session.diff`. The update named model
`deepseek-v4.1-flash-free`, provider `opencode`, version `1.19.0`, cost `0`.
The provider then emitted this bounded raw status fragment:

```json
{"type":"retry","attempt":1,"message":"Free usage exceeded, subscribe to Go","action":{"reason":"free_tier_limit","provider":"opencode","title":"Free limit reached","message":"Subscribe to OpenCode Go for reliable access to the best open-source models for $10/month.","label":"subscribe","link":"https://opencode.ai/go"},"next":1792108801405}
```

The subscription text is the provider's raw error, not a recommendation or an
action taken. No subscription or paid retry was made. **Zero before/after tool
events** fired, so neither read-tool arguments nor output shape are established.
The Python result recorded `timeout_seconds: 70`, empty stdout and empty stderr.
Tooling limitation: the Windows Bun launcher spawned an OpenCode child; killing
the launcher on timeout left that child holding captured pipes open. After
verifying the child's exact synthetic `run --agent spike ...` command line and
creation time, this reviewer stopped that child PID explicitly. The earlier
unrelated OpenCode process was left untouched. No spike process was left waiting
for the provider retry time.

`opencode-after-shape.json` preserves the actual session event structures,
replacing opaque session/event ids and local paths with stable placeholders.
Public model/provider identifiers are retained for reproducibility. The fixture
contains no invented after payload.

## Decision

Keep OpenCode F-08 runtime mapping unverified until a free session can actually
execute a tool. Use the implemented Claude adapter as the current adapter path;
its repository tests do not by themselves prove installed Claude host execution.
This spike is plugin-load and provider-error evidence only. No production plugin
implementation, source changes, commits, or paid calls were made.
