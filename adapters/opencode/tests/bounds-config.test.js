/**
 * Bounds and configuration: explicit opt-in, fail-closed misconfiguration,
 * clamped limits and the memory/identity overflow behaviours (sessions, pending,
 * acknowledged calls, uri length, response cap without honest content-length).
 */

import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { LIMITS, loadConfig, validateBaseUrl } from "../pedigree-core.js";
import { PedigreePlugin } from "../pedigree.js";
import { defaultServer, eventCalls, expectThrow, makeCore, makeProject, removeProject } from "./helpers.js";

const ARGS = { args: {} };

test("operator credentials are rejected locally before networking", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const config = loadConfig({ PEDIGREE_OPENCODE_ENABLED: "1", PEDIGREE_OPENCODE_TOKEN: "ped_o_synthetic_operator_only" });
  assert.deepEqual(config.problems, ["agent_token"]);
  const { core, calls } = makeCore({ project, config });
  const error = await expectThrow(core.beforeHook(
    { tool: "read", sessionID: "ses_role", callID: "call_role" },
    { args: { filePath: path.join(project, "dummy.txt") } },
  ));
  assert.equal(error.code, "misconfigured");
  assert.match(error.message, /agent token/);
  assert.deepEqual(calls, []);
  for (const token of ["ped_a_synthetic_agent", "ped_legacytenant_synthetic"])
    assert.deepEqual(loadConfig({ PEDIGREE_OPENCODE_ENABLED: "1", PEDIGREE_OPENCODE_TOKEN: token }).problems, []);
});

function readPair(project, callID, sessionID = "ses_bounds") {
  const filePath = path.join(project, "dummy.txt");
  return [
    { tool: "read", sessionID, callID },
    { args: { filePath } },
    { tool: "read", sessionID, callID, args: { filePath } },
    {
      title: "x",
      output: "y",
      metadata: {
        display: { type: "file", path: filePath, text: "v1", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false },
      },
    },
  ];
}

test("the plugin registers nothing unless explicitly enabled with =1", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const saved = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith("PEDIGREE_OPENCODE_")) delete process.env[key];
    }
    Object.assign(process.env, saved);
  });

  for (const value of [undefined, "0", "true", "yes", "enabled", ""]) {
    if (value === undefined || value === "") delete process.env.PEDIGREE_OPENCODE_ENABLED;
    else process.env.PEDIGREE_OPENCODE_ENABLED = value;
    delete process.env.PEDIGREE_OPENCODE_TOKEN;
    const hooks = await PedigreePlugin({ directory: project, worktree: project });
    assert.deepEqual(hooks, {}, `no hooks for PEDIGREE_OPENCODE_ENABLED=${JSON.stringify(value)}`);
  }
});

test("enabled but misconfigured plugins fail closed before any network call", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const saved = { ...process.env };
  t.after(() => {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith("PEDIGREE_OPENCODE_")) delete process.env[key];
    }
    Object.assign(process.env, saved);
  });
  for (const key of Object.keys(process.env)) {
    if (key.startsWith("PEDIGREE_OPENCODE_")) delete process.env[key];
  }

  // No token.
  process.env.PEDIGREE_OPENCODE_ENABLED = "1";
  delete process.env.PEDIGREE_OPENCODE_TOKEN;
  const noToken = await PedigreePlugin({ worktree: project });
  assert.deepEqual(Object.keys(noToken).sort(), ["tool.execute.after", "tool.execute.before"]);
  const tokenError = await expectThrow(
    noToken["tool.execute.before"]({ tool: "read", sessionID: "s1", callID: "c1" }, { args: { filePath: path.join(project, "dummy.txt") } }),
  );
  assert.equal(tokenError.code, "misconfigured");

  // Plaintext HTTP to a non-loopback endpoint.
  process.env.PEDIGREE_OPENCODE_TOKEN = "synthetic-token-env";
  process.env.PEDIGREE_OPENCODE_URL = "http://pedigree.example.com:8000";
  const remote = await PedigreePlugin({ worktree: project });
  const urlError = await expectThrow(
    remote["tool.execute.before"]({ tool: "read", sessionID: "s2", callID: "c2" }, { args: { filePath: path.join(project, "dummy.txt") } }),
  );
  assert.equal(urlError.code, "misconfigured");

  // No project root at all.
  delete process.env.PEDIGREE_OPENCODE_URL;
  const rootless = await PedigreePlugin({});
  const rootError = await expectThrow(
    rootless["tool.execute.before"]({ tool: "read", sessionID: "s3", callID: "c3" }, { args: { filePath: "dummy.txt" } }),
  );
  assert.equal(rootError.code, "misconfigured");
});

test("base URLs: HTTPS anywhere, plaintext only on loopback, no credentials or query", () => {
  const ok = ["http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:9", "https://pedigree.example.com", "https://127.0.0.1:8443"];
  for (const url of ok) assert.equal(validateBaseUrl(url), null, url);
  assert.equal(validateBaseUrl("http://pedigree.example.com"), "plaintext");
  assert.equal(validateBaseUrl("http://192.168.1.5:8000"), "plaintext");
  assert.equal(validateBaseUrl("http://user:pass@127.0.0.1:8000"), "credentials");
  assert.equal(validateBaseUrl("http://127.0.0.1:8000/?tenant=x"), "query");
  assert.equal(validateBaseUrl("http://127.0.0.1:8000/#frag"), "query");
  assert.equal(validateBaseUrl("ftp://127.0.0.1:8000"), "scheme");
  assert.equal(validateBaseUrl("not a url"), "invalid");
});

test("configuration numbers are clamped to the documented bounds", () => {
  const base = { PEDIGREE_OPENCODE_ENABLED: "1", PEDIGREE_OPENCODE_TOKEN: "t" };
  assert.deepEqual(loadConfig({}).problems, [], "a disabled adapter is not a misconfiguration");
  assert.deepEqual(loadConfig(base).problems, []);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_TIMEOUT_MS: "1" }).timeoutMs, 100);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_TIMEOUT_MS: "999999" }).timeoutMs, 30_000);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_TIMEOUT_MS: "abc" }).timeoutMs, 3000);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_MAX_RESPONSE_BYTES: "1" }).responseBytes, 4096);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_MAX_RESPONSE_BYTES: "999999999" }).responseBytes, 8 * LIMITS.responseBytes);
  assert.equal(loadConfig({ ...base, PEDIGREE_OPENCODE_MAX_RESPONSE_BYTES: "65536" }).responseBytes, 65536);
  assert.deepEqual(loadConfig({ ...base, PEDIGREE_OPENCODE_URL: "http://remote.example.com" }).problems, ["url"]);
  assert.deepEqual(loadConfig({ PEDIGREE_OPENCODE_ENABLED: "1" }).problems, ["token"]);
});

test("trailing slashes in the base URL never double up", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project, config: { baseUrl: "http://127.0.0.1:9///" } });
  const [bIn, bOut] = readPair(project, "call_slash");
  await core.beforeHook(bIn, bOut);
  assert.ok(calls.every((c) => c.url.startsWith("http://127.0.0.1:9/v1/")), calls[0].url);
});

test("the response cap holds even when content-length lies", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core } = makeCore({
    project,
    config: { responseBytes: 4096 },
    handler: (record) => {
      if (record.url.endsWith("/v1/gate")) {
        return { rawText: JSON.stringify({ decision: "allow", pad: "x".repeat(20_000) }), contentLength: 10 };
      }
      return defaultServer(record);
    },
  });
  const [bIn, bOut] = readPair(project, "call_pad");
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "endpoint_unavailable");
});

test("session state is bounded: the oldest evicted session cannot reappear silently", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core } = makeCore({ project });
  for (let i = 0; i < LIMITS.sessions; i++) {
    const [bIn, bOut] = readPair(project, `call_${i}`, `ses_fill_${i}`);
    await core.beforeHook(bIn, bOut);
  }
  let snapshot = core.snapshot();
  assert.equal(Object.keys(snapshot).length, LIMITS.sessions);
  const oldest = Object.keys(snapshot)[0];

  const [nIn, nOut] = readPair(project, "call_newest", `ses_fill_${LIMITS.sessions}`);
  await core.beforeHook(nIn, nOut); // creating one more evicts the oldest
  snapshot = core.snapshot();
  assert.equal(Object.keys(snapshot).length, LIMITS.sessions);
  assert.equal(snapshot[oldest], undefined, "the oldest session is gone from live state");

  const [rIn, rOut] = readPair(project, "call_return", "ses_fill_0");
  const error = await expectThrow(core.beforeHook(rIn, rOut));
  assert.equal(error.code, "incomplete", "the evicted session reappears latched, never blank");
  assert.equal(core.snapshot()[oldest].incomplete, "state_evicted");
});

test("pending and acknowledged call memory are capped per session", async (t) => {
  const project = makeProject();

  const pending = makeCore({ project });
  for (let i = 0; i < LIMITS.pendingPerSession; i++) {
    const [bIn, bOut] = readPair(project, `call_p_${i}`, "ses_pending");
    await pending.core.beforeHook(bIn, bOut); // gated, never completed
  }
  const pSnapshot = Object.values(pending.core.snapshot())[0];
  assert.equal(pSnapshot.pending, LIMITS.pendingPerSession);
  const [overflowIn, overflowOut] = readPair(project, "call_p_overflow", "ses_pending");
  const overflow = await expectThrow(pending.core.beforeHook(overflowIn, overflowOut));
  assert.equal(overflow.code, "incomplete");
  assert.equal(Object.values(pending.core.snapshot())[0].incomplete, "pending_overflow");

  const acked = makeCore({ project });
  const total = LIMITS.ackedPerSession + 1;
  for (let i = 0; i < total; i++) {
    const [bIn, bOut, aIn, aOut] = readPair(project, `call_a_${i}`, "ses_acked");
    await acked.core.beforeHook(bIn, bOut);
    await acked.core.afterHook(aIn, aOut);
  }
  assert.equal(eventCalls(acked.calls, total).body.events.length, 3, "the last capture landed");
  assert.equal(Object.values(acked.core.snapshot())[0].acked, LIMITS.ackedPerSession, "ack memory is capped");
  t.after(() => removeProject(project));
});

test("a read view whose URI would exceed the server limit is a capture gap, never a truncation", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const longName = `${"a".repeat(500)}.txt`;
  const filePath = path.join(project, longName);
  const [bIn, bOut, aIn, aOut] = readPair(project, "call_uri");
  bOut.args.filePath = filePath;
  aIn.args.filePath = filePath;
  aOut.metadata.display = { type: "file", path: filePath, text: "v1", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false };

  await core.beforeHook(bIn, bOut); // gated and pending
  assert.equal(calls.filter((c) => c.url.endsWith("/v1/gate")).length, 1, "the read was gated before completion");
  await core.afterHook(aIn, aOut);

  const snapshot = Object.values(core.snapshot())[0];
  assert.equal(snapshot.incomplete, "uri_overflow");
  assert.equal(eventCalls(calls, 1), undefined, "no capture batch was attempted");
  assert.ok((`readview:v1/${core.projectKey}/${longName}#L1-L1`).length > LIMITS.uri, "the constructed uri really would overflow");
});
