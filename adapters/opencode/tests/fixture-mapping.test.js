/**
 * Genuine-fixture mapping tests: the observed OpenCode 1.19.0 read hooks must
 * produce the exact allowlisted REST contract, with a versioned read-view
 * identity (uri + descriptor digest).
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { serverSessionId } from "../pedigree-core.js";
import {
  DUMMY_DISPLAY_TEXT,
  eventCalls,
  expectedDigest,
  fixtureHooks,
  gateCall,
  loadGenuineFixture,
  makeCore,
  makeProject,
  realKey,
  removeProject,
} from "./helpers.js";

test("genuine fixture maps to the exact allowlisted REST contract", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const sid = "ses_genuine_01";
  const fixture = loadGenuineFixture({ project, sessionID: sid, callID: "call_genuine_01" });
  const { before, after } = fixtureHooks(fixture);

  const result = await core.beforeHook(before.input, before.output);
  assert.deepEqual(result, { decision: "allow" }, "gate allow lets the read proceed");
  const afterResult = await core.afterHook(after.input, after.output);
  assert.deepEqual(afterResult, { captured: true });

  const serverSid = serverSessionId(realKey(project), sid);
  assert.deepEqual(
    calls.map((c) => c.url.replace(/^http:\/\/127\.0\.0\.1:9/, "")),
    ["/v1/events", "/v1/gate", "/v1/events"],
    "session ensure, then gate, then one capture batch",
  );
  for (const call of calls) {
    assert.equal(call.method, "POST");
    assert.equal(call.redirect, "error", "redirects are refused on every request");
    assert.equal(call.headers.Authorization, "Bearer synthetic-token");
    assert.equal(call.headers["Content-Type"], "application/json");
  }

  assert.deepEqual(eventCalls(calls, 0).body, {
    runtime: "opencode",
    session_id: serverSid,
    events: [{ type: "session" }],
  });

  assert.deepEqual(gateCall(calls, 0).body, {
    action: { tool: "read", summary: "read dummy.txt", effect: "reversible", risk: "low" },
    session_id: serverSid,
    record: false,
  });

  const capture = eventCalls(calls, 1).body;
  assert.equal(capture.runtime, "opencode");
  assert.equal(capture.session_id, serverSid);
  assert.equal(capture.events.length, 3);
  assert.deepEqual(capture.events[0], { type: "session" });
  const source = capture.events[1];
  const digest = expectedDigest({
    rel: "dummy.txt",
    lineStart: 1,
    lineEnd: 1,
    totalLines: 1,
    truncated: false,
    text: DUMMY_DISPLAY_TEXT,
  });
  assert.deepEqual(Object.keys(source).sort(), ["content_hash", "id", "source_kind", "uri", "type"].sort());
  assert.equal(source.type, "source_read");
  assert.equal(source.source_kind, "file");
  assert.match(source.id, /^src_oc_[0-9a-f]{16}$/);
  assert.equal(source.content_hash, digest, "digest covers the observed display view only");
  assert.equal(source.uri, `readview:v1/${realKey(project)}/dummy.txt#L1-L1`);
  assert.deepEqual(capture.events[2], { type: "session_read", node_id: source.id });

  const snapshot = core.snapshot()[serverSid];
  assert.equal(snapshot.incomplete, null);
  assert.equal(snapshot.pending, 0);
  assert.equal(snapshot.acked, 1);
  // No body, preview, output wrapper, title or absolute path anywhere on the wire.
  const wire = JSON.stringify(calls);
  assert.ok(!wire.includes(DUMMY_DISPLAY_TEXT), "display text is never sent");
  assert.ok(!wire.includes(project), "absolute project path is never sent");
  assert.ok(!wire.includes("<not transmitted>"));
});

test("repeat reads of the same view converge on one uri+digest", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const fixture = loadGenuineFixture({ project, sessionID: "ses_repeat", callID: "call_a" });
  await core.beforeHook(fixture.tool_events[0].input, fixture.tool_events[0].output);
  await core.afterHook(fixture.tool_events[1].input, fixture.tool_events[1].output);
  const second = loadGenuineFixture({ project, sessionID: "ses_repeat", callID: "call_b" });
  await core.beforeHook(second.tool_events[0].input, second.tool_events[0].output);
  await core.afterHook(second.tool_events[1].input, second.tool_events[1].output);

  const first = eventCalls(calls, 1).body.events[1];
  const again = eventCalls(calls, 2).body.events[1];
  assert.notEqual(first.id, again.id, "capture ids are per-call");
  assert.equal(first.uri, again.uri);
  assert.equal(first.content_hash, again.content_hash, "identity converges on (uri, digest)");
});

test("changed observed text keeps the uri and changes the digest", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const fixture = loadGenuineFixture({ project, sessionID: "ses_ver", callID: "call_v1" });
  await core.beforeHook(fixture.tool_events[0].input, fixture.tool_events[0].output);
  await core.afterHook(fixture.tool_events[1].input, fixture.tool_events[1].output);

  const second = loadGenuineFixture({ project, sessionID: "ses_ver", callID: "call_v2" });
  await core.beforeHook(second.tool_events[0].input, second.tool_events[0].output);
  const changed = structuredClone(second.tool_events[1]);
  changed.output.metadata.display.text = DUMMY_DISPLAY_TEXT + " changed";
  await core.afterHook(changed.input, changed.output);

  const first = eventCalls(calls, 1).body.events[1];
  const next = eventCalls(calls, 2).body.events[1];
  assert.equal(first.uri, next.uri);
  assert.notEqual(first.content_hash, next.content_hash, "a new version is a new identity");
});

test("changed range and truncation change uri and digest without any file read", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  fs.writeFileSync(path.join(project, "multi.txt"), "line one\nline two\nline three\n");
  const { core, calls } = makeCore({ project });

  async function readRange(callID, display) {
    const filePath = path.join(project, "multi.txt");
    await core.beforeHook({ tool: "read", sessionID: "ses_range", callID }, { args: { filePath } });
    await core.afterHook(
      { tool: "read", sessionID: "ses_range", callID, args: { filePath } },
      { title: filePath, output: "x", metadata: { display: { type: "file", path: filePath, ...display } } },
    );
  }

  await readRange("call_r1", { text: "line two", lineStart: 2, lineEnd: 2, totalLines: 3, truncated: false });
  await readRange("call_r2", { text: "line two", lineStart: 2, lineEnd: 3, totalLines: 3, truncated: false });
  await readRange("call_r3", { text: "line two", lineStart: 2, lineEnd: 2, totalLines: 3, truncated: true });

  const [a, b, c] = [1, 2, 3].map((n) => eventCalls(calls, n).body.events[1]);
  assert.equal(a.uri, `readview:v1/${realKey(project)}/multi.txt#L2-L2`);
  assert.equal(b.uri, `readview:v1/${realKey(project)}/multi.txt#L2-L3`);
  assert.notEqual(a.content_hash, b.content_hash);
  assert.equal(a.uri, c.uri);
  assert.notEqual(a.content_hash, c.content_hash, "truncation is part of the observed descriptor");
  // None of these file bodies appear anywhere on the wire.
  assert.ok(!JSON.stringify(calls).includes("line one"));
  assert.ok(!JSON.stringify(calls).includes("line three"));
});

test("server session ids are namespaced by project and runtime session", async (t) => {
  const projectA = makeProject();
  const projectB = makeProject();
  t.after(() => {
    removeProject(projectA);
    removeProject(projectB);
  });
  const sid = "ses_same_id";
  const a = makeCore({ project: projectA });
  const b = makeCore({ project: projectB });
  const fx = loadGenuineFixture({ project: projectA, sessionID: sid, callID: "call_a" });
  await a.core.beforeHook(fx.tool_events[0].input, fx.tool_events[0].output);
  const fxB = loadGenuineFixture({ project: projectB, sessionID: sid, callID: "call_a" });
  await b.core.beforeHook(fxB.tool_events[0].input, fxB.tool_events[0].output);

  const idA = gateCall(a.calls, 0).body.session_id;
  const idB = gateCall(b.calls, 0).body.session_id;
  assert.notEqual(idA, idB, "the same runtime session string in another project is another server session");
  assert.equal(idA, serverSessionId(realKey(projectA), sid));

  const hostile = serverSessionId(realKey(projectA), "weird session id! \u0000[]");
  assert.match(hostile, /^oc_p_[0-9a-f]{16}_h[0-9a-f]{32}$/);
  assert.ok(hostile.length <= 128);
});
