/**
 * Shared test helpers for the Pedigree OpenCode adapter suite.
 * Builtin Node only (node:test, node:assert, node:crypto, node:fs).
 */

import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createCore, projectKeyFor } from "../pedigree-core.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, "..", "..", "..");
export const FIXTURE_PATH = path.join(REPO_ROOT, "docs", "consults", "opencode-recheck-2026-10-16-shape.json");

const REALPATH = typeof fs.realpathSync.native === "function" ? fs.realpathSync.native : fs.realpathSync;

/** Canonical on-disk root, matching the core's resolver (native realpath when available). */
export function canonicalRoot(project) {
  return REALPATH(project);
}

/** Expected project key for a fixture directory, computed independently of the core. */
export function realKey(project) {
  return projectKeyFor(canonicalRoot(project));
}

export const DUMMY_CONTENT = "Synthetic public Pedigree capture recheck. Marker: F08_RECHECK_DUMMY_READ_OK.\n";
export const DUMMY_DISPLAY_TEXT = "Synthetic public Pedigree capture recheck. Marker: F08_RECHECK_DUMMY_READ_OK.";

export function makeProject() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pedigree-opencode-"));
  fs.writeFileSync(path.join(dir, "dummy.txt"), DUMMY_CONTENT);
  return dir;
}

export function removeProject(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    /* best effort for a temp fixture */
  }
}

/**
 * Load the genuine installed-runtime fixture (OpenCode 1.19.0 read hooks) and
 * substitute its sanitization placeholders. Values are JSON-escaped so the
 * fixture's literal `\\` separators round-trip.
 */
export function loadGenuineFixture({ project, sessionID = "ses_test_0001", callID = "call_test_0001" }) {
  // The captured fixture uses Windows separators. Substitute the real dummy file
  // with this platform's separator so Linux does not treat "\" as a filename.
  const projectFile = JSON.stringify(path.join(project, "dummy.txt")).slice(1, -1);
  const projectDir = JSON.stringify(project).slice(1, -1);
  const raw = fs
    .readFileSync(FIXTURE_PATH, "utf8")
    .replaceAll("$SESSION_ID", JSON.stringify(sessionID).slice(1, -1))
    .replaceAll("$CALL_ID", JSON.stringify(callID).slice(1, -1))
    .replaceAll("$PROJECT\\\\dummy.txt", projectFile)
    .replaceAll("$PROJECT/dummy.txt", projectFile)
    .replaceAll("$PROJECT", projectDir);
  return JSON.parse(raw);
}

export function fixtureHooks(fixture) {
  const [before, after] = fixture.tool_events;
  return { before, after };
}

/** A fake fetch that records calls and answers from a handler. */
export function makeFetch(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    const record = {
      url: String(url),
      method: init && init.method,
      headers: (init && init.headers) || {},
      redirect: init && init.redirect,
      body: init && typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(record);
    const out = (await handler(record, calls.length)) ?? {};
    if (out.networkError) {
      const error = new Error("synthetic network failure");
      error.name = out.networkError;
      throw error;
    }
    if (out.rawText !== undefined) return jsonResponse(out.rawText, out.status ?? 200, out.contentLength, true);
    return jsonResponse(out.data ?? {}, out.status ?? 200, out.contentLength);
  };
  return { fetchImpl, calls };
}

function jsonResponse(data, status, contentLength, preEncoded = false) {
  const text = preEncoded ? String(data) : JSON.stringify(data);
  const bytes = Buffer.from(text, "utf8");
  let sent = false;
  const body = {
    getReader() {
      return {
        async read() {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: new Uint8Array(bytes) };
        },
        async cancel() {},
      };
    },
  };
  return {
    status,
    headers: {
      get: (name) => (String(name).toLowerCase() === "content-length" ? String(contentLength ?? bytes.byteLength) : null),
    },
    body,
    async text() {
      return text;
    },
  };
}

/** Route-aware default server behaviour: gate allows, capture acknowledges. */
export function defaultServer(record) {
  if (record.url.endsWith("/v1/gate")) return { data: { decision: "allow", reasons: [], checked: 0 } };
  if (record.url.endsWith("/v1/events")) return { data: { created: ["src_captured"] } };
  return { data: {} };
}

export function makeCore(options = {}) {
  const project = options.project ?? makeProject();
  const config = {
    enabled: true,
    baseUrl: "http://127.0.0.1:9",
    token: "synthetic-token",
    timeoutMs: 1000,
    responseBytes: 65536,
    problems: [],
    ...(options.config || {}),
  };
  const { fetchImpl, calls } = makeFetch(options.handler ?? defaultServer);
  const logs = [];
  const core = createCore({
    config,
    projectRoot: options.projectRoot ?? project,
    fetchImpl,
    log: (message) => logs.push(String(message)),
    now: options.now,
  });
  return { project, config, core, calls, logs };
}

export function sha256Hex(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

/** Independent canonical-encoding digest (must not import the core's own codec). */
export function expectedDigest({ rel, lineStart, lineEnd, totalLines, truncated, text }) {
  const canonical =
    `{"v":1,"path":${JSON.stringify(rel)},"line_start":${lineStart},"line_end":${lineEnd},` +
    `"total_lines":${totalLines},"truncated":${truncated},"text":${JSON.stringify(text)}}`;
  return sha256Hex(canonical);
}

export function gateCall(calls, n) {
  return calls.filter((c) => c.url.endsWith("/v1/gate"))[n];
}

export function eventCalls(calls, n) {
  return calls.filter((c) => c.url.endsWith("/v1/events"))[n];
}

/** Replay one read through both hooks using the genuine after-hook display shape. */
export async function replayRead(core, { project, sessionID, callID, file = "dummy.txt", args = {} }) {
  const absolute = path.join(project, file);
  const before = await core.beforeHook(
    { tool: "read", sessionID, callID },
    { args: { filePath: absolute, ...args } },
  );
  const after = await core.afterHook(
    { tool: "read", sessionID, callID, args: { filePath: absolute } },
    {
      title: absolute,
      output: "<not transmitted>",
      metadata: {
        preview: DUMMY_DISPLAY_TEXT,
        truncated: false,
        loaded: [],
        display: {
          type: "file",
          path: absolute,
          text: DUMMY_DISPLAY_TEXT,
          lineStart: 1,
          lineEnd: 1,
          totalLines: 1,
          truncated: false,
        },
      },
    },
  );
  return { before, after };
}

export async function expectThrow(promise, code) {
  try {
    await promise;
  } catch (error) {
    if (code !== undefined) {
      if (error.code !== code) throw new Error(`expected code ${code}, got ${error.code}: ${error.message}`);
    }
    return error;
  }
  throw new Error(`expected a Pedigree denial (${code}) but the operation resolved`);
}
