/**
 * Path containment and observed-view validation: traversal, symlink/junction
 * escapes, credential exclusions, directory reads, inconsistent paths and the
 * display-metadata matrix.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { isCredentialPath, resolveWithinRoot } from "../pedigree-core.js";
import { canonicalRoot, defaultServer, expectThrow, gateCall, makeCore, makeProject, removeProject } from "./helpers.js";

const SID = "ses_paths";

function hookPair(project, callID, filePath, display = {}) {
  const shown = display.path ?? filePath;
  return [
    { tool: "read", sessionID: SID, callID },
    { args: { filePath } },
    { tool: "read", sessionID: SID, callID, args: { filePath } },
    {
      title: "x",
      output: "y",
      metadata: {
        display: {
          type: "file",
          path: shown,
          text: "v1",
          lineStart: 1,
          lineEnd: 1,
          totalLines: 1,
          truncated: false,
          ...display,
        },
      },
    },
  ];
}

test("traversal and outside-root reads are denied before any network call", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const outside = path.join(project, "..", "outside.txt");
  for (const candidate of [outside, "..\\..\\Windows\\system.ini", "/etc/passwd", "sub/../../escape.txt"]) {
    const [bIn, bOut] = hookPair(project, "call_p", candidate);
    const error = await expectThrow(core.beforeHook(bIn, bOut));
    assert.equal(error.code, "path_outside", `denied: ${candidate}`);
  }
  assert.equal(calls.length, 0);
});

test("credential-excluded paths are denied; near-miss names are allowed", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core } = makeCore({ project });
  for (const candidate of [".env", ".env.local", "sub/.env.production", "secrets.pem", "signing.key", ".ssh/id_rsa", "certs/keystore.jks", ".aws/credentials"]) {
    const [bIn, bOut] = hookPair(project, "call_c", candidate);
    const error = await expectThrow(core.beforeHook(bIn, bOut));
    assert.equal(error.code, "path_credential", `denied: ${candidate}`);
  }
  assert.equal(isCredentialPath(".environment"), false);
  assert.equal(isCredentialPath("keys.pub"), false);
  const [okIn, okOut] = hookPair(project, "call_ok", ".environment");
  const result = await core.beforeHook(okIn, okOut);
  assert.deepEqual(result, { decision: "allow" });
});

test("a symlink or junction escaping the project is denied", async (t) => {
  const project = makeProject();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "pedigree-outside-"));
  t.after(() => {
    removeProject(project);
    removeProject(outside);
  });
  fs.writeFileSync(path.join(outside, "secret.txt"), "outside content");

  let escapePath = null;
  try {
    escapePath = path.join(project, "linkdir");
    fs.symlinkSync(outside, escapePath, "junction");
  } catch {
    try {
      escapePath = path.join(project, "linkfile.txt");
      fs.symlinkSync(path.join(outside, "secret.txt"), escapePath, "file");
    } catch {
      escapePath = null;
    }
  }
  if (escapePath === null) {
    t.skip("symlinks are not creatable in this environment");
    return;
  }
  const candidate = fs.statSync(escapePath).isDirectory() ? path.join(escapePath, "secret.txt") : escapePath;
  const { core, calls } = makeCore({ project });
  const [bIn, bOut] = hookPair(project, "call_s", candidate);
  const error = await expectThrow(core.beforeHook(bIn, bOut));
  assert.equal(error.code, "path_outside");
  assert.equal(calls.length, 0);

  // Textual resolution must also never leak the outside path as a relative one.
  const textual = resolveWithinRoot(canonicalRoot(project), candidate);
  assert.ok(textual.denied === "path_outside" || !textual.rel.startsWith(".."));
});

test("a missing file inside the project is still gated (the tool reports its own error)", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const [bIn, bOut] = hookPair(project, "call_missing", "not-there-yet.txt");
  await core.beforeHook(bIn, bOut);
  assert.deepEqual(
    calls.map((c) => (c.url.endsWith("/v1/gate") ? "gate" : "events")),
    ["events", "gate"],
  );
});

test("directory reads and inconsistent display paths become capture gaps (never silent)", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  fs.mkdirSync(path.join(project, "subdir"));

  const directory = makeCore({ project });
  const [dirIn, dirOut, dirAfterIn, dirAfterOut] = hookPair(project, "call_dir", "subdir", { type: "directory" });
  await directory.core.beforeHook(dirIn, dirOut);
  assert.deepEqual(await directory.core.afterHook(dirAfterIn, dirAfterOut), undefined);
  assert.equal(directory.core.snapshot()[Object.keys(directory.core.snapshot())[0]].incomplete, "invalid_display");

  const mismatch = makeCore({ project });
  const [mIn, mOut, mAfterIn, mAfterOut] = hookPair(project, "call_mismatch", "dummy.txt", { path: "subdir" });
  await mismatch.core.beforeHook(mIn, mOut);
  await mismatch.core.afterHook(mAfterIn, mAfterOut);
  assert.equal(mismatch.core.snapshot()[Object.keys(mismatch.core.snapshot())[0]].incomplete, "path_mismatch");
  assert.equal(mismatch.calls.filter((c) => c.body && c.body.events && c.body.events.length === 3).length, 0);

  const escaped = makeCore({ project });
  const [eIn, eOut, eAfterIn, eAfterOut] = hookPair(project, "call_esc", "dummy.txt", { path: path.join(project, "..", "outside.txt") });
  await escaped.core.beforeHook(eIn, eOut);
  await escaped.core.afterHook(eAfterIn, eAfterOut);
  assert.equal(escaped.core.snapshot()[Object.keys(escaped.core.snapshot())[0]].incomplete, "path_mismatch");
});

test("relative display paths resolve to the same observed view as absolute ones", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const { core, calls } = makeCore({ project });
  const [bIn, bOut, aIn, aOut] = hookPair(project, "call_rel", path.join(project, "dummy.txt"), { path: "dummy.txt" });
  await core.beforeHook(bIn, bOut);
  await core.afterHook(aIn, aOut);
  const capture = calls.find((c) => c.body && c.body.events && c.body.events.length === 3);
  assert.ok(capture.body.events[1].uri.endsWith("/dummy.txt#L1-L1"));
});

test("the observed-view validation matrix is complete", async (t) => {
  const project = makeProject();
  t.after(() => removeProject(project));
  const base = { type: "file", path: "dummy.txt", text: "v1", lineStart: 1, lineEnd: 1, totalLines: 1, truncated: false };
  const cases = [
    ["missing display", undefined],
    ["not an object", "x"],
    ["wrong type", { ...base, type: "directory" }],
    ["missing path", { ...base, path: undefined }],
    ["missing text", { ...base, text: undefined }],
    ["lineStart 0", { ...base, lineStart: 0 }],
    ["lineEnd before start", { ...base, lineEnd: 0 }],
    ["totalLines below end", { ...base, totalLines: 0 }],
    ["truncated not boolean", { ...base, truncated: "no" }],
    ["fractional range", { ...base, lineEnd: 1.5 }],
    ["oversized text", { ...base, text: "a".repeat(4 * 1024 * 1024 + 1) }],
  ];
  for (const [label, display] of cases) {
    const { core, calls } = makeCore({ project });
    const [bIn, bOut, aIn] = hookPair(project, "call_v", path.join(project, "dummy.txt"));
    await core.beforeHook(bIn, bOut);
    await core.afterHook(aIn, { title: "x", output: "y", metadata: display === undefined ? {} : { display } });
    const snapshot = core.snapshot();
    assert.equal(snapshot[Object.keys(snapshot)[0]].incomplete, "invalid_display", label);
    assert.equal(calls.filter((c) => c.body && c.body.events && c.body.events.length === 3).length, 0, label);
  }
});

test(
  "win32: alternate-stream and drive-relative forms are denied before any network call",
  { skip: process.platform !== "win32" },
  async (t) => {
    const project = makeProject();
    t.after(() => removeProject(project));
    fs.writeFileSync(path.join(project, "id_rsa"), "stream canary bytes");
    const { core, calls } = makeCore({ project });
    const candidates = [
      "dummy.txt::$DATA",
      "id_rsa::$DATA",
      `${path.join(project, "dummy.txt")}:stream`,
      "C:dummy.txt",
      "Z:anywhere.txt",
    ];
    for (const candidate of candidates) {
      const [bIn, bOut] = hookPair(project, "call_w32", candidate);
      const error = await expectThrow(core.beforeHook(bIn, bOut));
      assert.equal(error.code, "path_stream", `denied: ${candidate}`);
    }
    const root = canonicalRoot(project);
    assert.equal(resolveWithinRoot(root, "id_rsa::$DATA").denied, "path_stream");
    assert.equal(resolveWithinRoot(root, "C:dummy.txt").denied, "path_stream");
    // The genuine absolute fixture form (drive followed by a separator) is not affected.
    const [okIn, okOut] = hookPair(project, "call_w32_ok", path.join(project, "dummy.txt"));
    assert.deepEqual(await core.beforeHook(okIn, okOut), { decision: "allow" });
    assert.deepEqual(calls.map((c) => (c.url.endsWith("/v1/gate") ? "gate" : "events")), ["events", "gate"]);
  },
);

test(
  "win32: case-variant paths canonicalize to one observed view",
  { skip: process.platform !== "win32" },
  async (t) => {
    const project = makeProject();
    t.after(() => removeProject(project));
    fs.writeFileSync(path.join(project, "case.txt"), "case canary\n", "utf8");
    const { core, calls } = makeCore({ project });
    const upper = path.join(project, "CASE.TXT");
    const lower = path.join(project, "case.txt");
    for (const [callID, candidate] of [["call_case_upper", upper], ["call_case_lower", lower]]) {
      const [bIn, bOut] = hookPair(project, callID, candidate);
      assert.deepEqual(await core.beforeHook(bIn, bOut), { decision: "allow" }, candidate);
    }
    assert.equal(gateCall(calls, 0).body.action.summary, "read case.txt");
    assert.equal(gateCall(calls, 1).body.action.summary, "read case.txt");
    const root = canonicalRoot(project);
    assert.deepEqual(resolveWithinRoot(root, upper), { rel: "case.txt" });
    assert.deepEqual(resolveWithinRoot(root, lower), { rel: "case.txt" });
  },
);
