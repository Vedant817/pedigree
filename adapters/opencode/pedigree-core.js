/**
 * Pedigree OpenCode capture core (F-08 observed native tools).
 *
 * Dependency-free ESM. Pure mappers plus an injected `fetchImpl`; `pedigree.js`
 * supplies the thin OpenCode hooks. Scope and limits: docs/features/F-08-opencode.md
 * and docs/DECISIONS.md ADR-009.
 *
 * Guarantees implemented here:
 * - Only observed native read/write/edit/bash shapes are supported. Other tools
 *   and unobserved argument forms are denied before execution.
 * - Reads are validated (project containment, credential exclusions, symlink
 *   escapes, Windows drive-relative/alternate-stream forms) and gated through
 *   POST /v1/gate; block/reverify/unknown decisions and gate outages deny the read.
 * - A completed read is captured as session + observed read view + read edge via
 *   POST /v1/events. The digest covers only the observed display view (text,
 *   range, truncation); no file bodies, output wrappers, commands or absolute
 *   paths are transmitted.
 * - Failed/ambiguous capture latches the session incomplete, which denies all
 *   further operations for that session.
 *
 * - Mutations are conservatively gated as unknown/high. Verified successful
 *   file results become hash-only artifacts/actions; successful Bash output is
 *   an untrusted hash-only source. Nonzero/unknown outcomes latch the session.
 * Explicitly out of scope: approval UX, durable replay/ack state across plugin
 * restarts, arbitrary Bash filesystem provenance and cross-session write links.
 */

import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export class PedigreeOpenCodeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "PedigreeOpenCodeError";
    this.code = code;
  }
}

export const LIMITS = Object.freeze({
  //: Server-side contract limits (src/pedigree/config.py LIMITS).
  uri: 512,
  summary: 300,
  //: Local bounds.
  pathChars: 1024,
  displayBytes: 4 * 1024 * 1024,
  responseBytes: 1024 * 1024,
  sessions: 64,
  pendingPerSession: 64,
  ackedPerSession: 512,
  evictedRemembered: 256,
});

export const READVIEW_SCHEME = "readview:v1";
export const PROJECT_SALT = "pedigree.opencode.project.v1|";

const REPOINT = "pedigree: ";

/**
 * Canonical on-disk path resolver. The native variant canonicalizes the case of
 * existing paths on Windows (`GetFinalPathNameByHandle`), so `CASE.TXT` and
 * `case.txt` resolve to one identity; the JS fallback preserves the caller's
 * case for existing files.
 */
const REALPATH = typeof fs.realpathSync.native === "function" ? fs.realpathSync.native : fs.realpathSync;

/**
 * Windows-only path forms that must be denied before resolution:
 * - `C:relative` (drive-relative) resolves against the process current directory
 *   of drive C, not the project root, so `path.resolve` and the runtime tool can
 *   open different files;
 * - any colon after the drive prefix selects an NTFS alternate data stream
 *   (e.g. `notes.txt:stream`, `id_rsa::$DATA`), whose contents are not covered
 *   by the credential basename checks.
 * On POSIX both forms are ordinary file names and are allowed.
 */
export function isDeniedWin32Form(candidate) {
  if (process.platform !== "win32") return false;
  if (/^[A-Za-z]:(?![\\/])/.test(candidate)) return true;
  const afterDrive = /^[A-Za-z]:/.test(candidate) ? candidate.slice(2) : candidate;
  if (afterDrive.includes(":")) return true;
  // Win32 normalizes trailing dots/spaces and resolves device basenames.
  // Reject aliases before a new credential path can bypass basename checks.
  return afterDrive.split(/[\\/]/).some(segment =>
    (segment !== "." && segment !== ".." && /[. ]$/.test(segment))
    || /^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i.test(segment));
}

/** Sanitized, fixed error texts. Never include content, absolute paths, tokens or exception details. */
export const MESSAGES = Object.freeze({
  disabled: `${REPOINT}adapter is not enabled`,
  misconfigured: `${REPOINT}adapter configuration is invalid; an agent token is required; denying all tools (fail-closed)`,
  unsupported: (tool) => `${REPOINT}tool "${tool}" is not supported by this capture adapter and was denied`,
  malformed: `${REPOINT}tool hook payload is malformed; operation denied`,
  incomplete: `${REPOINT}session capture is incomplete; further operations are denied`,
  path_outside: `${REPOINT}read denied; path is outside the configured project`,
  path_credential: `${REPOINT}read denied; path is excluded from capture`,
  path_stream: `${REPOINT}read denied; drive-relative and alternate-stream path forms are not supported`,
  duplicate_call: `${REPOINT}duplicate tool call identity; operation denied`,
  gate_block: `${REPOINT}read denied by gate (block)`,
  gate_reverify: `${REPOINT}read denied by gate (reverify)`,
  gate_unknown: `${REPOINT}read denied; gate returned an unknown decision`,
  endpoint_unavailable: `${REPOINT}read denied; Pedigree endpoint is unavailable`,
});

/** Native shapes observed in installed OpenCode 1.19.3 (consult 015). */
const SUPPORTED_TOOLS = new Set(["read", "write", "edit", "bash"]);
const NATIVE_ARGUMENT_KEYS = Object.freeze({
  write: ["filePath", "content"],
  edit: ["filePath", "oldString", "newString"],
  bash: ["command"],
});

function nativeFingerprint(tool, args) {
  if (!args || typeof args !== "object" || Array.isArray(args)
      || Object.keys(args).some(key => !NATIVE_ARGUMENT_KEYS[tool].includes(key))) {
    throw deny("malformed");
  }
  return tool === "bash" ? digestBytes(args.command)
    : digestBytes(JSON.stringify(NATIVE_ARGUMENT_KEYS[tool].map(key => args[key])));
}

function deny(reason, tool) {
  const message = typeof MESSAGES[reason] === "function" ? MESSAGES[reason](tool) : MESSAGES[reason];
  return new PedigreeOpenCodeError(reason, message);
}

function clampInt(raw, fallback, min, max) {
  const n = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

// ---- configuration ----------------------------------------------------------

export function loadConfig(env = {}) {
  const enabled = env.PEDIGREE_OPENCODE_ENABLED === "1";
  const baseUrl = String(env.PEDIGREE_OPENCODE_URL || "http://127.0.0.1:8000").trim();
  const token = String(env.PEDIGREE_OPENCODE_TOKEN || "");
  const timeoutMs = clampInt(env.PEDIGREE_OPENCODE_TIMEOUT_MS, 3000, 100, 30000);
  const responseBytes = clampInt(env.PEDIGREE_OPENCODE_MAX_RESPONSE_BYTES, LIMITS.responseBytes, 4096, 8 * LIMITS.responseBytes);
  const problems = [];
  if (enabled) {
    if (validateBaseUrl(baseUrl) !== null) problems.push("url");
    if (!token) problems.push("token");
    if (token.trim().startsWith("ped_o_")) problems.push("agent_token");
  }
  return { enabled, baseUrl, token, timeoutMs, responseBytes, problems };
}

/** The endpoint must be HTTPS unless loopback, carry no credentials and no query/fragment. */
export function validateBaseUrl(baseUrl) {
  let url;
  try {
    url = new URL(baseUrl);
  } catch {
    return "invalid";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "scheme";
  if (url.username || url.password) return "credentials";
  if (url.search || url.hash) return "query";
  if (url.protocol === "http:" && !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
    return "plaintext";
  }
  return null;
}

// ---- pure path/identity helpers --------------------------------------------

export function projectKeyFor(realRoot) {
  return "p_" + createHash("sha256").update(`${PROJECT_SALT}${realRoot}`, "utf8").digest("hex").slice(0, 16);
}

const CREDENTIAL_BASENAMES = new Set([
  ".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
  "credentials", "credentials.json", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
]);
const CREDENTIAL_EXTENSIONS = new Set([".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk"]);
const CREDENTIAL_SEGMENTS = new Set([".ssh", ".aws", ".gnupg", ".docker", ".kube"]);

export function isCredentialPath(rel) {
  const segments = String(rel).split("/");
  const base = segments[segments.length - 1].toLowerCase();
  if (CREDENTIAL_BASENAMES.has(base) || base.startsWith(".env.")) return true;
  const dot = base.lastIndexOf(".");
  if (dot > 0 && CREDENTIAL_EXTENSIONS.has(base.slice(dot))) return true;
  return segments.some((s) => CREDENTIAL_SEGMENTS.has(s.toLowerCase()));
}

/** Containment test on a `path.relative` result. A `..` *segment* escapes the
 *  root; names merely starting with `..` (`..x`, `..foo`) are literal children. */
function escapesRoot(rel) {
  return rel === ".." || rel.startsWith(".." + path.sep) || path.isAbsolute(rel);
}

/**
 * Resolve `candidate` against the canonical project root. Symlinks/junctions and
 * `..` escapes outside the root are denied; relative path is returned with `/`.
 */
export function resolveWithinRoot(rootReal, candidate) {
  if (typeof candidate !== "string" || !candidate || candidate.length > LIMITS.pathChars || candidate.includes("\0")) {
    return { denied: "malformed" };
  }
  if (isDeniedWin32Form(candidate)) return { denied: "path_stream" };
  let abs;
  try {
    abs = path.resolve(rootReal, candidate);
  } catch {
    return { denied: "malformed" };
  }
  const relText = path.relative(rootReal, abs);
  if (escapesRoot(relText)) return { denied: "path_outside" };

  let real = null;
  try {
    real = REALPATH(abs);
  } catch {
    // New files still need their nearest existing parent's canonical location.
    // A textual child of an escaping junction must never become a permitted write.
    let parent = path.dirname(abs);
    while (parent !== path.dirname(parent)) {
      try {
        const parentReal = REALPATH(parent);
        if (escapesRoot(path.relative(rootReal, parentReal))) return { denied: "path_outside" };
        real = path.join(parentReal, path.relative(parent, abs));
        break;
      } catch {
        parent = path.dirname(parent);
      }
    }
  }
  let rel = relText;
  if (real) {
    const relReal = path.relative(rootReal, real);
    if (escapesRoot(relReal)) return { denied: "path_outside" };
    rel = relReal;
  }
  rel = rel === "" ? "." : rel.split(path.sep).join("/");
  return { rel };
}

function digestBytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function boundedFile(rootReal, rel) {
  const abs = path.join(rootReal, ...rel.split("/"));
  const fd = fs.openSync(abs, "r");
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > LIMITS.displayBytes) throw deny("malformed");
    // Keep the allocation bounded even if another writer grows the file.
    const buffer = Buffer.alloc(LIMITS.displayBytes + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = fs.readSync(fd, buffer, length, buffer.length - length, null);
      if (count === 0) break;
      length += count;
    }
    if (length > LIMITS.displayBytes) throw deny("malformed");
    return buffer.subarray(0, length);
  } finally {
    fs.closeSync(fd);
  }
}

function nativeArguments(tool, args, rootReal, resolvePath) {
  if (!args || typeof args !== "object" || Array.isArray(args)) throw deny("malformed");
  if (tool === "bash") {
    if (Object.keys(args).some(k => k !== "command") || typeof args.command !== "string"
        || !args.command || Buffer.byteLength(args.command) > LIMITS.displayBytes) throw deny("malformed");
    return { fingerprint: digestBytes(args.command), commandHash: digestBytes(args.command) };
  }
  const allowed = NATIVE_ARGUMENT_KEYS[tool];
  if (Object.keys(args).some(k => !allowed.includes(k))) throw deny("malformed");
  const resolved = resolvePath(args.filePath);
  if (resolved.denied) throw deny(resolved.denied);
  if (isCredentialPath(resolved.rel)) throw deny("path_credential");
  let expected;
  if (tool === "write") {
    if (typeof args.content !== "string" || Buffer.byteLength(args.content) > LIMITS.displayBytes) throw deny("malformed");
    expected = args.content;
  } else {
    if (typeof args.oldString !== "string" || !args.oldString || typeof args.newString !== "string"
        || Buffer.byteLength(args.oldString) + Buffer.byteLength(args.newString) > LIMITS.displayBytes) throw deny("malformed");
    const bytes = boundedFile(rootReal, resolved.rel);
    const old = bytes.toString("utf8");
    if (!Buffer.from(old).equals(bytes)) throw deny("malformed");
    if (old.indexOf(args.oldString) < 0 || old.indexOf(args.oldString) !== old.lastIndexOf(args.oldString)) throw deny("malformed");
    expected = old.replace(args.oldString, () => args.newString);
    if (Buffer.byteLength(expected) > LIMITS.displayBytes) throw deny("malformed");
  }
  return {
    rel: resolved.rel,
    expectedHash: digestBytes(expected),
    fingerprint: nativeFingerprint(tool, args),
  };
}

/** Validate the observed after-hook display view. Only `file` displays with a
 *  complete, consistent range/truncation record are capturable. */
export function validateDisplay(display, maxBytes = LIMITS.displayBytes) {
  if (!display || typeof display !== "object") return { denied: "display_missing" };
  if (display.type !== "file") return { denied: "display_type" };
  if (typeof display.path !== "string" || !display.path) return { denied: "display_path" };
  if (typeof display.text !== "string") return { denied: "display_text" };
  const { lineStart, lineEnd, totalLines, truncated } = display;
  if (!Number.isInteger(lineStart) || lineStart < 1) return { denied: "display_range" };
  if (!Number.isInteger(lineEnd) || lineEnd < lineStart) return { denied: "display_range" };
  if (!Number.isInteger(totalLines) || totalLines < lineEnd) return { denied: "display_range" };
  if (typeof truncated !== "boolean") return { denied: "display_range" };
  if (Buffer.byteLength(display.text, "utf8") > maxBytes) return { denied: "display_oversized" };
  return { ok: { path: display.path, text: display.text, lineStart, lineEnd, totalLines, truncated } };
}

/** Versioned descriptor over the observed display view. Key order is the wire identity. */
export function descriptorFor(rel, view) {
  return {
    v: 1,
    path: rel,
    line_start: view.lineStart,
    line_end: view.lineEnd,
    total_lines: view.totalLines,
    truncated: view.truncated,
    text: view.text,
  };
}

export function descriptorDigest(descriptor) {
  return createHash("sha256").update(JSON.stringify(descriptor), "utf8").digest("hex");
}

export function readViewUri(projectKey, rel, lineStart, lineEnd) {
  return `${READVIEW_SCHEME}/${projectKey}/${rel}#L${lineStart}-L${lineEnd}`;
}

/** Namespace the runtime session id by project and keep it inside the server id grammar. */
export function serverSessionId(projectKey, sessionID) {
  const safe = /^[A-Za-z0-9_.@:#-]{1,96}$/.test(sessionID)
    ? sessionID
    : "h" + createHash("sha256").update(sessionID, "utf8").digest("hex").slice(0, 32);
  return `oc_${projectKey}_${safe}`;
}

// ---- transport --------------------------------------------------------------

/**
 * Bounded POST transport. `fetchImpl` is injected so failures are testable.
 * Returns { ok: true, status, data } or { ok: false, failure: transport|timeout|
 * status|too_large|bad_json }.
 */
export async function requestJson({ fetchImpl, url, token, body, timeoutMs, responseBytes }) {
  const fetchFn = fetchImpl || globalThis.fetch;
  if (typeof fetchFn !== "function") return { ok: false, failure: "transport" };
  let res;
  try {
    res = await fetchFn(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    return { ok: false, failure: error && error.name === "TimeoutError" ? "timeout" : "transport" };
  }
  if (!(res.status >= 200 && res.status < 300)) return { ok: false, failure: "status", status: res.status };
  const declared = res.headers && typeof res.headers.get === "function" ? Number(res.headers.get("content-length")) : NaN;
  if (Number.isFinite(declared) && declared > responseBytes) return { ok: false, failure: "too_large" };
  let text;
  try {
    if (res.body && typeof res.body.getReader === "function") {
      const reader = res.body.getReader();
      const chunks = [];
      let received = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        received += value.byteLength;
        if (received > responseBytes) {
          try { await reader.cancel(); } catch { /* bounded */ }
          return { ok: false, failure: "too_large" };
        }
        chunks.push(Buffer.from(value));
      }
      text = Buffer.concat(chunks).toString("utf8");
    } else {
      text = await res.text();
      if (Buffer.byteLength(text, "utf8") > responseBytes) return { ok: false, failure: "too_large" };
    }
  } catch {
    return { ok: false, failure: "transport" };
  }
  try {
    return { ok: true, status: res.status, data: JSON.parse(text) };
  } catch {
    return { ok: false, failure: "bad_json", status: res.status };
  }
}

// ---- core -------------------------------------------------------------------

export function createCore({ config, projectRoot, workingDirectory, fetchImpl, now = Date.now, log = () => {} }) {
  const problems = [...(config.problems || [])];
  let rootReal = null;
  if (typeof projectRoot === "string" && projectRoot) {
    try {
      rootReal = REALPATH(projectRoot);
    } catch {
      rootReal = null;
    }
  }
  if (!rootReal) problems.push("project");
  let directoryReal = rootReal;
  if (workingDirectory) {
    try {
      directoryReal = REALPATH(workingDirectory);
      if (!rootReal || escapesRoot(path.relative(rootReal, directoryReal))) problems.push("directory");
    } catch {
      problems.push("directory");
    }
  }
  const projectKey = rootReal ? projectKeyFor(rootReal) : null;
  const base = config.baseUrl.replace(/\/+$/, "");

  const sessions = new Map();
  const evicted = new Set();
  const evictedOrder = [];

  function resolvePath(candidate) {
    if (typeof candidate !== "string" || !candidate || candidate.length > LIMITS.pathChars || candidate.includes("\0")) {
      return {denied: "malformed"};
    }
    if (isDeniedWin32Form(candidate)) return {denied: "path_stream"};
    return resolveWithinRoot(rootReal, path.resolve(directoryReal, candidate));
  }

  function newSession(serverSid) {
    return {
      serverSid,
      chain: Promise.resolve(),
      ensured: false,
      incomplete: null,
      pending: new Map(),
      acked: new Set(),
      unsupported: 0,
      lastUsed: now(),
    };
  }

  function evictOne() {
    let oldest = null;
    for (const [sid, s] of sessions) {
      if (oldest === null || s.lastUsed < sessions.get(oldest).lastUsed) oldest = sid;
    }
    if (oldest === null) return;
    sessions.delete(oldest);
    evicted.add(oldest);
    evictedOrder.push(oldest);
    while (evictedOrder.length > LIMITS.evictedRemembered) {
      evicted.delete(evictedOrder.shift());
    }
  }

  function sessionFor(rawSid) {
    const serverSid = serverSessionId(projectKey || "nokey", rawSid);
    let session = sessions.get(serverSid);
    if (session) {
      session.lastUsed = now();
      return session;
    }
    session = newSession(serverSid);
    if (evicted.has(serverSid)) latch(session, "state_evicted");
    if (sessions.size >= LIMITS.sessions) evictOne();
    sessions.set(serverSid, session);
    return session;
  }

  function enqueue(session, task) {
    const next = session.chain.then(task, task);
    session.chain = next.then(() => {}, () => {});
    return next;
  }

  function latch(session, reason) {
    if (session.incomplete) return;
    session.incomplete = reason;
    try {
      log(`${REPOINT}capture incomplete (${reason}); further operations denied`);
    } catch { /* logging must never break enforcement */ }
  }

  function ackAdd(session, callID) {
    if (session.acked.size >= LIMITS.ackedPerSession) {
      const oldest = session.acked.values().next().value;
      session.acked.delete(oldest);
    }
    session.acked.add(callID);
  }

  async function post(pathSuffix, body) {
    return requestJson({
      fetchImpl,
      url: base + pathSuffix,
      token: config.token,
      body,
      timeoutMs: config.timeoutMs,
      responseBytes: config.responseBytes,
    });
  }

  function summaryFor(rel) {
    const raw = `read ${rel}`;
    return raw.length > LIMITS.summary ? raw.slice(0, LIMITS.summary) : raw;
  }

  async function beforeHook(input, output) {
    if (!config.enabled) throw deny("disabled");
    if (problems.length) throw deny("misconfigured");
    const tool = input && typeof input.tool === "string" ? input.tool : "";
    const rawSid = input && typeof input.sessionID === "string" ? input.sessionID : "";
    const callID = input && typeof input.callID === "string" ? input.callID : "";
    if (!rawSid) throw deny("malformed");
    const session = sessionFor(rawSid);
    return enqueue(session, async () => {
      session.lastUsed = now();
      if (!SUPPORTED_TOOLS.has(tool)) {
        session.unsupported += 1;
        const safeTool = tool.replace(/[^\w.:-]/g, "?").slice(0, 64);
        throw deny("unsupported", safeTool);
      }
      if (!callID) {
        latch(session, "malformed_call");
        throw deny("malformed");
      }
      if (session.incomplete) throw deny("incomplete");
      if (session.pending.size && (tool !== "read" || [...session.pending.values()].some(p=>p.tool !== "read"))) {
        latch(session,"unresolved_native_call");
        throw deny("incomplete");
      }
      let prepared;
      if (tool === "read") {
        const filePath = output && output.args ? output.args.filePath : undefined;
        if (typeof filePath !== "string" || !filePath) {
          latch(session, "malformed_path");
          throw deny("malformed");
        }
        prepared = resolvePath(filePath);
        if (prepared.denied) throw deny(prepared.denied);
        if (isCredentialPath(prepared.rel)) throw deny("path_credential");
      } else {
        try {
          prepared = nativeArguments(tool, output?.args, rootReal, resolvePath);
        } catch (error) {
          // Filesystem failures must not expose absolute paths or OS diagnostics.
          if (error instanceof PedigreeOpenCodeError) throw error;
          throw deny("malformed");
        }
        if (tool !== "bash") {
          const versionKey = `file:v1/${projectKey}/${prepared.rel}@${prepared.expectedHash}`;
          if (versionKey.length > LIMITS.uri || /[\x00-\x1f]/.test(versionKey)) throw deny("malformed");
        }
      }
      if (session.pending.has(callID) || session.acked.has(callID)) {
        latch(session, "duplicate_call");
        throw deny("duplicate_call");
      }
      if (session.pending.size >= LIMITS.pendingPerSession) {
        latch(session, "pending_overflow");
        throw deny("incomplete");
      }

      if (!session.ensured) {
        const ensured = await post("/v1/events", {
          runtime: "opencode",
          session_id: session.serverSid,
          events: [{ type: "session" }],
        });
        if (!ensured.ok) throw deny("endpoint_unavailable");
        session.ensured = true;
      }

      const gated = await post("/v1/gate", {
        action: tool === "read"
          ? { tool: "read", summary: summaryFor(prepared.rel), effect: "reversible", risk: "low" }
          : { tool, summary: tool === "bash" ? `bash sha256:${prepared.commandHash}` : `${tool} ${prepared.rel}`.slice(0,LIMITS.summary), effect: "unknown", risk: "high" },
        session_id: session.serverSid,
        record: false,
      });
      if (!gated.ok) throw deny("endpoint_unavailable");
      const decision = gated.data && gated.data.decision;
      if (decision === "block") throw deny("gate_block");
      if (decision === "reverify") throw deny("gate_reverify");
      if (decision !== "allow" && decision !== "warn") throw deny("gate_unknown");

      session.pending.set(callID, { ...prepared, tool, decision, at: now() });
      return { decision };
    });
  }

  async function afterHook(input, output) {
    if (!config.enabled || problems.length) return;
    const rawSid = input && typeof input.sessionID === "string" ? input.sessionID : "";
    if (!rawSid) return;
    const session = sessionFor(rawSid);
    return enqueue(session, async () => {
      session.lastUsed = now();
      const tool = input && typeof input.tool === "string" ? input.tool : "";
      if (!SUPPORTED_TOOLS.has(tool)) return; // the before hook denied it; nothing executed
      if (session.incomplete) return;
      const callID = input && typeof input.callID === "string" ? input.callID : "";
      if (!callID) {
        latch(session, "malformed_call");
        return;
      }
      if (session.acked.has(callID)) return; // duplicate replay: never capture twice
      const pending = session.pending.get(callID);
      if (!pending) {
        latch(session, "uncaptured_call");
        return;
      }
      session.pending.delete(callID);

      if (pending.tool !== tool) {
        latch(session, "tool_mismatch");
        return;
      }
      if (tool !== "read") {
        let events;
        try {
          // Reconstructing an edit after execution is impossible; bind its original
          // canonical arguments and compare the intended result digest instead.
          const args = input.args;
          const fingerprint = nativeFingerprint(tool, args);
          if (fingerprint !== pending.fingerprint) throw deny("malformed");
          const metadata = output?.metadata;
          if (!metadata || metadata.truncated !== false) throw deny("malformed");
          if (tool === "bash") {
            if (!Number.isInteger(metadata.exit) || metadata.exit !== 0
                || typeof metadata.output !== "string" || metadata.output !== output.output
                || Buffer.byteLength(metadata.output) > LIMITS.displayBytes) throw deny("malformed");
            const digest = digestBytes(metadata.output);
            const sourceId = "src_oc_" + randomBytes(8).toString("hex");
            events = [{type:"session"},
              {type:"action_executed",tool,summary:`bash sha256:${pending.commandHash} exit=0`,decision:pending.decision,effect:"unknown",risk:"high"},
              {type:"source_read",source_kind:"tool_output",id:sourceId,uri:`tooloutput:v1/${projectKey}/${digest}`,content_hash:digest},
              {type:"session_read",node_id:sourceId}];
          } else {
            // Revalidate the actual requested path as well as the reported path.
            // Metadata may use the former canonical target of a replaced symlink.
            const requested = resolvePath(args.filePath);
            if (requested.denied || requested.rel !== pending.rel || isCredentialPath(requested.rel)) throw deny("malformed");
            const metadataPath = tool === "write" ? metadata.filepath : metadata.filediff?.file;
            const resolved = resolvePath(metadataPath);
            if (resolved.denied || resolved.rel !== pending.rel || isCredentialPath(resolved.rel)) throw deny("malformed");
            if (tool === "write" && typeof metadata.exists !== "boolean") throw deny("malformed");
            if (tool === "edit" && (!Number.isInteger(metadata.filediff.additions)
                || !Number.isInteger(metadata.filediff.deletions))) throw deny("malformed");
            const digest = digestBytes(boundedFile(rootReal, pending.rel));
            if (digest !== pending.expectedHash) throw deny("malformed");
            const artifact = `file:v1/${projectKey}/${pending.rel}`;
            if (artifact.length > LIMITS.uri) throw deny("malformed");
            events = [{type:"session"},{type:"action_executed",tool,
              summary:`${tool} ${pending.rel} sha256:${digest}`.slice(0,LIMITS.summary),
              artifacts:[artifact],artifact_key:`${artifact}@${digest}`,decision:pending.decision,effect:"unknown",risk:"high"}];
          }
        } catch {
          latch(session,"invalid_native_result");
          return;
        }
        const captured = await post("/v1/events", {runtime:"opencode",session_id:session.serverSid,events});
        if (captured.ok && Array.isArray(captured.data?.created) && captured.data.created.length >= 1) {
          ackAdd(session,callID);
          return {captured:true};
        }
        latch(session,"capture_failed");
        return {captured:false};
      }

      const displayView = output && output.metadata ? output.metadata.display : undefined;
      const view = validateDisplay(displayView);
      if (view.denied) {
        latch(session, "invalid_display");
        return;
      }
      const shown = resolvePath(view.ok.path);
      if (shown.denied || shown.rel !== pending.rel) {
        latch(session, "path_mismatch");
        return;
      }

      const digest = descriptorDigest(descriptorFor(pending.rel, view.ok));
      const uri = readViewUri(projectKey, pending.rel, view.ok.lineStart, view.ok.lineEnd);
      if (uri.length > LIMITS.uri) {
        latch(session, "uri_overflow");
        return;
      }
      const captureId = "src_oc_" + randomBytes(8).toString("hex");
      const captured = await post("/v1/events", {
        runtime: "opencode",
        session_id: session.serverSid,
        events: [
          { type: "session" },
          { type: "source_read", source_kind: "file", id: captureId, uri, content_hash: digest },
          { type: "session_read", node_id: captureId },
        ],
      });
      if (captured.ok && Array.isArray(captured.data && captured.data.created) && captured.data.created.length >= 1) {
        ackAdd(session, callID);
        session.ensured = true;
        return { captured: true };
      }
      latch(session, "capture_failed");
      return { captured: false };
    });
  }

  function snapshot() {
    const out = {};
    for (const [sid, s] of sessions) {
      out[sid] = {
        incomplete: s.incomplete,
        pending: s.pending.size,
        acked: s.acked.size,
        unsupported: s.unsupported,
        ensured: s.ensured,
      };
    }
    return out;
  }

  return { beforeHook, afterHook, snapshot, projectKey, projectRoot: rootReal, configProblems: problems };
}
