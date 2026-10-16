/**
 * Hook replay driver for the F-08 OpenCode adapter.
 *
 * Runs a scripted sequence of OpenCode plugin hooks through the real plugin
 * entry (`pedigree.js` -> `pedigree-core.js`) and prints one JSON report.
 *
 * Usage:
 *   PEDIGREE_OPENCODE_ENABLED=1 PEDIGREE_OPENCODE_URL=http://127.0.0.1:<port> \
 *   PEDIGREE_OPENCODE_TOKEN=<tenant token> node driver.js job.json
 *
 * Job JSON: {"project": "<absolute dir>", "hooks": [{"phase": "before"|"after",
 * "input": {...}, "output": {...}}, ...]}
 *
 * Exit code 0 whenever the job ran to completion; per-hook denials are outcomes
 * (`{ok: false, code, message}`), not dispatcher errors. This replays recorded
 * hook payloads (docs/consults/opencode-recheck-2026-10-16-shape.json); it does
 * not run an installed OpenCode session.
 */

import fs from "node:fs";
import process from "node:process";

import { PedigreePlugin } from "../pedigree.js";

const jobPath = process.argv[2];
if (!jobPath) {
  console.error("usage: node driver.js <job.json>");
  process.exit(2);
}

const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
if (typeof job.project !== "string" || !job.project) {
  console.error("driver job is missing a project directory");
  process.exit(2);
}

const plugin = await PedigreePlugin({ directory: job.project, worktree: job.project });
const results = [];
for (const hook of job.hooks ?? []) {
  const name = hook.phase === "after" ? "tool.execute.after" : "tool.execute.before";
  const handler = plugin[name];
  if (typeof handler !== "function") {
    results.push({ ok: false, code: "not_registered" });
    continue;
  }
  try {
    const value = await handler(hook.input, hook.output);
    results.push({ ok: true, value: value === undefined ? null : value });
  } catch (error) {
    results.push({
      ok: false,
      code: error && error.code ? error.code : "driver_error",
      message: String((error && error.message) || error),
    });
  }
}
process.stdout.write(`${JSON.stringify({ results })}\n`);
