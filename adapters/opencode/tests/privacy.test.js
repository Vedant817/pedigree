/**
 * Privacy canaries: only the allowlisted wire shapes may leave the process.
 * File bytes, output wrappers, previews, titles, commands, absolute paths and
 * the operator credential are never transmitted; denial texts and latch logs
 * stay fixed and sanitized.
 */

import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { MESSAGES } from "../pedigree-core.js";
import {
  canonicalRoot,
  defaultServer,
  eventCalls,
  expectThrow,
  expectedDigest,
  fixtureHooks,
  gateCall,
  loadGenuineFixture,
  makeCore,
  makeProject,
  realKey,
  removeProject,
} from "./helpers.js";

const SID = "ses_privacy";

/** Every key that may appear anywhere in a request body (allowlist scan). */
const ALLOWED_BODY_KEYS = new Set([
  "action", "tool", "summary", "effect", "risk",
  "session_id", "record",
  "runtime", "events",
  "type", "source_kind", "id", "uri", "content_hash", "node_id",
]);

function assertAllowlistedKeys(value, label) {
  if (Array.isArray(value)) {
    for (const item of value) assertAllowlistedKeys(item, label);
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      assert.ok(ALLOWED_BODY_KEYS.has(key), `${label}: unexpected wire key "${key}"`);
      assertAllowlistedKeys(item, label);
    }
  }
}

test("canaries in file bytes, output, preview, title, args and paths never reach the wire", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));

  // Assembled at runtime so the scanner never sees a credential-shaped literal.
  const TOKEN = ["CANARY", "OPERATOR", "TOKEN", "6c1f"].join("_");
  const FILE_BYTES = "CANARY_FILE_BYTES_e83a";
  const COMMAND = "CANARY_COMMAND_rm_rf_11b0";
  const PREVIEW = "CANARY_PREVIEW_97d2";
  const TITLE = "CANARY_TITLE_4a55";
  const ARGS = "CANARY_ARGS_pattern_20ce";
  const TEXT = "CANARY_OBSERVED_TEXT_never_wire_9f2c";

  const { core, calls } = makeCore({ project, config: { token: TOKEN } });
  const fixture = loadGenuineFixture({ project, sessionID: SID, callID: "call_priv_01" });
  const { before, after } = fixtureHooks(fixture);

  // The before-hook args carry more than the path; the after-hook carries the
  // full observed output. Everything except the display text field is canary.
  before.output.args.pattern = ARGS;
  after.output.title = TITLE;
  after.output.output = `<path>${path.join(project, "dummy.txt")}</path>\n<content>${FILE_BYTES}</content>\n<command>${COMMAND}</command>`;
  after.output.metadata.preview = PREVIEW;
  after.output.metadata.display.text = TEXT;

  assert.deepEqual(await core.beforeHook(before.input, before.output), { decision: "allow" });
  assert.deepEqual(await core.afterHook(after.input, after.output), { captured: true });

  // The digest commits to the observed display text without transmitting it.
  const source = eventCalls(calls, 1).body.events[1];
  assert.equal(
    source.content_hash,
    expectedDigest({ rel: "dummy.txt", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false, text: TEXT }),
  );

  // Identity is namespaced and relative; no absolute path can appear in it.
  assert.equal(source.uri, `readview:v1/${realKey(project)}/dummy.txt#L1-L1`);
  assert.ok(!source.uri.includes(project));
  assert.equal(gateCall(calls, 0).body.action.summary, "read dummy.txt");

  // Exact wire shapes: no unexpected keys anywhere.
  for (const [index, call] of calls.entries()) assertAllowlistedKeys(call.body, `call ${index} (${call.url})`);
  const keys = new Set();
  for (const call of calls) {
    for (const key of Object.keys(call.body)) keys.add(key);
  }
  assert.deepEqual(
    [...keys].sort(),
    ["action", "events", "record", "runtime", "session_id"],
    "top-level body keys are exactly the two contract shapes",
  );

  // No canary anywhere on the wire.
  const wire = JSON.stringify(calls.map((c) => c.body));
  for (const canary of [FILE_BYTES, COMMAND, PREVIEW, TITLE, ARGS, TEXT]) {
    assert.ok(!wire.includes(canary), `canary leaked: ${canary}`);
  }
  assert.ok(!wire.includes(project), "the absolute project path never reaches the wire");
  const wireEscaped = (text) => JSON.stringify(text).slice(1, -1);
  assert.ok(!wire.includes(wireEscaped(project)), "not even JSON-escaped");
  assert.ok(!wire.includes(wireEscaped(canonicalRoot(project))), "the canonical root never reaches the wire");
  assert.ok(!wire.includes("filePath"), "the raw args envelope is never forwarded");

  // The credential goes only into the Authorization header, never a body.
  for (const call of calls) {
    assert.equal(call.headers.Authorization, `Bearer ${TOKEN}`);
    assert.ok(!JSON.stringify(call.body).includes(TOKEN), "the token never appears in a body");
  }
});

test("denial texts and latch logs are fixed, sanitized strings", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core } = makeCore({ project });

  const credential = await expectThrow(
    core.beforeHook(
      { tool: "read", sessionID: SID, callID: "call_priv_02" },
      { args: { filePath: path.join(project, ".env") } },
    ),
  );
  assert.equal(credential.message, MESSAGES.path_credential);
  assert.ok(!credential.message.includes(project), "no absolute path in the denial");

  const hostileTool = `write ${path.join(project, "secret.txt")} "quoted"`;
  const unsupported = await expectThrow(
    core.beforeHook({ tool: hostileTool, sessionID: SID, callID: "call_priv_03" }, { args: {} }),
  );
  assert.equal(unsupported.code, "unsupported");
  assert.ok(!unsupported.message.includes(hostileTool), "the raw tool string is not echoed");
  assert.ok(!unsupported.message.includes(project), "the sanitized tool text cannot reconstruct the path");

  // A failed capture latches with exactly one fixed log line, free of payload.
  const failed = makeCore({
    project,
    handler: (record) => {
      if (record.url.endsWith("/v1/events") && record.body.events.length === 3) return { status: 500, data: {} };
      return defaultServer(record);
    },
  });
  const filePath = path.join(project, "dummy.txt");
  await failed.core.beforeHook({ tool: "read", sessionID: "ses_priv_latch", callID: "call_priv_04" }, { args: { filePath } });
  await failed.core.afterHook(
    { tool: "read", sessionID: "ses_priv_latch", callID: "call_priv_04", args: { filePath } },
    {
      title: "CANARY_TITLE",
      output: "CANARY_OUTPUT",
      metadata: {
        display: { type: "file", path: filePath, text: "CANARY_TEXT", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false },
      },
    },
  );
  assert.deepEqual(failed.logs, ["pedigree: capture incomplete (capture_failed); further operations denied"]);
});
