/**
 * Hook behaviour: gate decisions, failure handling, execution prevention,
 * pairing/serialization, dedup and the session-incomplete latch.
 */

import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { defaultServer, expectThrow, makeCore, makeProject, removeProject } from "./helpers.js";

const SID = "ses_hooks";

function gateDecision(decision, extra = {}) {
  return (record) => {
    if (record.url.endsWith("/v1/gate")) return { data: { decision, reasons: [], checked: 0, ...extra } };
    if (record.url.endsWith("/v1/events")) return { data: { created: ["src_captured"] } };
    return { data: {} };
  };
}

function readInputs(project, callID) {
  const filePath = path.join(project, "dummy.txt");
  return [
    { tool: "read", sessionID: SID, callID },
    { args: { filePath } },
    { tool: "read", sessionID: SID, callID, args: { filePath } },
    {
      title: filePath,
      output: "<not transmitted>",
      metadata: {
        display: { type: "file", path: filePath, text: "v1", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false },
      },
    },
  ];
}

test("gate allow and warn let the read through; a completed read is captured", async (t) => {
  for (const decision of ["allow", "warn"]) {
    const project = makeProject();
    t.after(() => removeProject(project));
    const { core, calls } = makeCore({ project, handler: gateDecision(decision) });
    const [bIn, bOut, aIn, aOut] = readInputs(project, "call_ok");
    let executed = false;
    await core.beforeHook(bIn, bOut);
    executed = true;
    await core.afterHook(aIn, aOut);
    assert.equal(executed, true, `${decision}: the read ran`);
    assert.equal(core.snapshot()[Object.keys(core.snapshot())[0]].incomplete, null);
    assert.equal(calls.length, 3);
  }
});

test("block, reverify, unknown or missing gate decisions deny before execution", async (t) => {
  for (const decision of ["block", "reverify", "sideways", undefined]) {
    const project = makeProject();
    t.after(() => removeProject(project));
    const { core } = makeCore({
      project,
      handler: gateDecision(decision),
    });
    const [bIn, bOut] = readInputs(project, "call_denied");
    let executed = false;
    const error = await expectThrow(
      (async () => {
        await core.beforeHook(bIn, bOut);
        executed = true;
      })(),
    );
    assert.equal(executed, false, `${decision}: the read must not execute`);
    assert.match(error.message, /^pedigree: /);
    assert.ok(!error.message.includes(project), "no absolute path in the denial");
    assert.ok(["gate_block", "gate_reverify", "gate_unknown"].includes(error.code), String(error.code));
  }
});

test("gate outages, HTTP errors, redirects, oversized and malformed responses deny without poisoning the session", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const failures = [
    { networkError: "TimeoutError", label: "timeout" },
    { networkError: "TypeError", label: "redirect refusal" },
    { status: 500, data: {}, label: "HTTP 500" },
    { rawText: "{not json", status: 200, label: "malformed JSON" },
    { data: {}, status: 200, contentLength: 10 * 1024 * 1024, label: "oversized response" },
  ];
  for (const failure of failures) {
    let serveFailures = true;
    const { core, calls } = makeCore({
      project,
      handler: (record) => {
        if (serveFailures && record.url.endsWith("/v1/gate")) return failure;
        return defaultServer(record);
      },
    });
    const [bIn, bOut, aIn, aOut] = readInputs(project, "call_fail");
    const error = await expectThrow(core.beforeHook(bIn, bOut));
    assert.equal(error.code, "endpoint_unavailable", failure.label);

    serveFailures = false;
    await core.beforeHook(bIn, bOut); // a healthy gate still works afterwards
    await core.afterHook(aIn, aOut);
    assert.equal(calls.filter((c) => c.url.endsWith("/v1/events")).length, 2, failure.label);
  }
});

test("a failed session ensure denies the read before any gate call", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({
    project,
    handler: (record) => (record.url.endsWith("/v1/events") ? { status: 503, data: {} } : defaultServer(record)),
  });
  const [bIn, bOut] = readInputs(project, "call_ensure");
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "endpoint_unavailable");
  assert.equal(calls.length, 1, "no gate request after a failed ensure");
});

test("every unsupported tool is denied before execution with zero network calls", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  let executed = false;
  for (const tool of ["apply_patch", "mcp__pedigree__blame", "task"]) {
    const error = await expectThrow(
      (async () => {
        await core.beforeHook({ tool, sessionID: SID, callID: "call_x" }, { args: {} });
        executed = true;
      })(),
    );
    assert.equal(error.code, "unsupported");
    assert.match(error.message, new RegExp(`"${tool.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`));
  }
  assert.equal(executed, false);
  assert.equal(calls.length, 0, "denials are local; nothing reaches the network");
  const snapshot = core.snapshot();
  assert.equal(snapshot[Object.keys(snapshot)[0]].unsupported, 3);
  assert.equal(snapshot[Object.keys(snapshot)[0]].incomplete, null, "a denied unsupported tool was not executed");
});

test("an after hook for an unsupported tool is ignored", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  await core.afterHook({ tool: "apply_patch", sessionID: SID, callID: "call_w" }, { title: "x", output: "y", metadata: {} });
  assert.equal(calls.length, 0);
  assert.equal(core.snapshot()[Object.keys(core.snapshot())[0]].incomplete, null);
});

test("capture acknowledgements serialize before the next gate (per session)", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  let release;
  const gateOpen = new Promise((resolve) => {
    release = resolve;
  });
  let heldCapture = false;
  const { core, calls } = makeCore({
    project,
    handler: async (record) => {
      if (record.url.endsWith("/v1/events") && record.body.events.length === 3 && !heldCapture) {
        heldCapture = true;
        await gateOpen;
      }
      return defaultServer(record);
    },
  });
  const [aIn, aOut, aAfterIn, aAfterOut] = readInputs(project, "call_a");
  const [bIn, bOut] = readInputs(project, "call_b");
  await core.beforeHook(aIn, aOut); // gate A resolves
  const flowA = core.afterHook(aAfterIn, aAfterOut); // capture A is held open
  const flowB = core.beforeHook(bIn, bOut); // B arrives while A's capture is unacknowledged
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.length, 3, "read B's gate waits for read A's capture acknowledgement");
  assert.ok(calls[2].url.endsWith("/v1/events"));
  release();
  await flowA;
  await flowB;
  assert.deepEqual(
    calls.map((c) => (c.url.endsWith("/v1/gate") ? "gate" : "events")),
    ["events", "gate", "events", "gate"],
  );
});

test("duplicate call identities latch the session; a replay after a completed capture does not recapture", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const [bIn, bOut, aIn, aOut] = readInputs(project, "call_dup");
  await core.beforeHook(bIn, bOut);
  await core.afterHook(aIn, aOut);
  const before = calls.length;
  await core.afterHook(aIn, aOut); // duplicate replay of a completed hook
  assert.equal(calls.length, before, "no second capture batch");

  const error = await expectThrow(core.beforeHook(bIn, emptyArgs()));
  assert.equal(error.code, "duplicate_call", "a duplicate pending call is ambiguous and denied");

  async function later() {
    const [b2, o2] = readInputs(project, "call_later");
    return expectThrow(core.beforeHook(b2, o2));
  }
  const latched = await later();
  assert.equal(latched.code, "incomplete", "the ambiguous duplicate latched the session");

  function emptyArgs() {
    return { args: { filePath: path.join(project, "dummy.txt") } };
  }
});

test("an after hook with no gated call is an ambiguous gap and latches the session", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const [bIn, bOut] = readInputs(project, "call_solo");
  await core.afterHook(bIn, bOut); // never went through the before hook
  assert.equal(calls.length, 0, "an unpaired after hook sends no capture");
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "incomplete");
});

test("a failed capture is completed-but-uncaptured: the after hook never throws, the session latches", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, logs } = makeCore({
    project,
    handler: (record) => {
      if (record.url.endsWith("/v1/events") && record.body.events.length === 3) return { status: 500, data: {} };
      return defaultServer(record);
    },
  });
  const [bIn, bOut, aIn, aOut] = readInputs(project, "call_capfail");
  await core.beforeHook(bIn, bOut);
  const result = await core.afterHook(aIn, aOut); // must resolve, not throw
  assert.deepEqual(result, { captured: false });
  assert.equal(logs.length, 1);
  assert.match(logs[0], /capture incomplete \(capture_failed\)/);
  assert.ok(!logs[0].includes(project), "the latch log is content- and path-free");
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "incomplete");
});

test("an events acknowledgement with an empty created list is not an acknowledgement", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core } = makeCore({
    project,
    handler: (record) => {
      if (record.url.endsWith("/v1/events") && record.body.events.length === 3) return { data: { created: [] } };
      return defaultServer(record);
    },
  });
  const [bIn, bOut, aIn, aOut] = readInputs(project, "call_empty");
  await core.beforeHook(bIn, bOut);
  assert.deepEqual(await core.afterHook(aIn, aOut), { captured: false });
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "incomplete");
});

test("malformed hook payloads are denied; malformed call identity latches", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  await expectThrow(core.beforeHook({ tool: "read" }, { args: {} }), "malformed");
  await expectThrow(core.beforeHook({ tool: "read", sessionID: "ses_m1" }, { args: {} }), "malformed");
  await expectThrow(core.beforeHook({ tool: "read", sessionID: "ses_m2", callID: "c1" }, { args: {} }), "malformed");
  await expectThrow(core.beforeHook({ tool: "read", sessionID: "ses_m3", callID: "c2" }, { args: { filePath: 42 } }), "malformed");
  assert.equal(calls.length, 0);
  const error = await expectThrow(
    core.beforeHook({ tool: "read", sessionID: "ses_m1", callID: "c3" }, { args: { filePath: path.join(project, "dummy.txt") } }),
  );
  assert.equal(error.code, "incomplete", "a malformed pair latched that session");
});
