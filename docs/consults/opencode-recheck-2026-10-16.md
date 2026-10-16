# OpenCode installed-runtime recheck, 2026-10-16

**One genuine read tool invocation captured both runtime hooks.** This removes
the previous blocker on the *read-tool payload shape*. It does not establish
complete capture, write-tool shapes, a completed agent conversation, or E6
coverage/friction measurements. The earlier quota-blocked fixture is unchanged.

## Free-only selection and isolation

Installed executable: `C:\Users\vedan\.bun\bin\opencode.exe`, version `1.19.0`.
The live `models opencode --verbose` catalog identified
`opencode/deepseek-v4.1-flash-free` as active, tool-call capable, with input,
output, cache-read and cache-write prices all zero. The main model, small model,
and explicit primary `spike` agent all used that exact identifier. Enabled
providers were restricted to `opencode`; there was no paid fallback and no
Claude invocation.

The session ran in a fresh `pedigree-opencode-recheck-*` temporary directory
outside the repository. Its project contained only a synthetic, read-only
`dummy.txt`, local configuration, an empty `.git` directory, and a temporary
plugin. The empty `.git` directory is not a valid initialized Git repository;
no repository-isolation claim relies on it. Separate temporary XDG config,
data, cache and state directories and `OPENCODE_CONFIG_DIR` isolated runtime
state. Inherited credential/provider/T3 variables were removed from the child
environment. Sharing and auto-update were disabled. The temporary environment
snapshot used to launch the child was deleted after execution.

The dummy file contained only:

```text
Synthetic public Pedigree capture recheck. Marker: F08_RECHECK_DUMMY_READ_OK.
```

Permissions denied every tool except reads; the plugin's before hook rejected
every tool/path combination except `read` of that exact dummy file. The plugin
logged only its before/after hook inputs and outputs, plus a separate first
retry/error status if one arose. No retry/error status arose. No private
repository files or credentials were supplied to the model.

## Exact single session and bounded result

```text
opencode.exe run --agent spike --model opencode/deepseek-v4.1-flash-free --format json --title "Synthetic F08 recheck 2026-10-16" "Read dummy.txt with the read tool exactly once and report the marker. Do not use any other tool."
```

The controller permitted one session, with a 60-second wall limit and immediate
termination on the first provider retry/error. The model executed exactly one
read. CLI JSON emitted `tool_use` with `state.status: "completed"`, followed by
`step_finish` with `reason: "tool-calls"` and `cost: 0`. The final assistant
response did not arrive before the wall limit; the controller stopped the
session process tree at 60.45 seconds. Its exit code was 1 after termination;
stderr was empty. A subsequent process check found no OpenCode process with
this synthetic session title. No second session or retry loop was launched.

## Established payload contract

The new [sanitized genuine fixture](opencode-recheck-2026-10-16-shape.json)
retains the real structures, replacing session/call IDs and temporary paths.

- `tool.execute.before`: input contains `tool`, `sessionID`, `callID`;
  output contains `args.filePath`.
- `tool.execute.after`: input additionally contains `args.filePath`;
  output contains `title`, `output` (the read-result string), and `metadata`.
- Read metadata contains `preview`, `truncated`, `loaded`, and a `display`
  object with file path, text and line boundaries.

These observations support implementing and testing this installed version's
read-hook mapping. They provide no write/patch/bash hook evidence and no
measurement of whether an adapter captures all dependencies in real work.
