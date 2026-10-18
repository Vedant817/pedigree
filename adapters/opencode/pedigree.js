/**
 * Pedigree OpenCode plugin entry (F-08 observed native tools).
 *
 * Install (see README.md): copy `pedigree.js` and `pedigree-core.js` into the
 * explicitly registered plugin directory (see README.md) and
 * set PEDIGREE_OPENCODE_ENABLED=1 plus PEDIGREE_OPENCODE_TOKEN for the session
 * that should be captured. Disabled unless explicitly enabled; when disabled
 * this module registers no hooks and sends nothing.
 *
 * This entry exports exactly one named plugin function, matching the verified
 * project-plugin shape (`export const Capture = ...` in the genuine recheck).
 *
 * Behaviour while enabled (docs/features/F-08-opencode.md):
 * - `read` is validated, gated via the local Pedigree API and captured as an
 *   observed read view (hash only; no file bytes leave the process).
 * - Observed write/edit/Bash forms are gated as unknown/high and captured only
 *   after their result is verified. All other tools are denied before execution.
 * - Failed/ambiguous capture latches the session incomplete and denies further
 *   operations; the session must be restarted.
 */

import { createCore, loadConfig } from "./pedigree-core.js";

export const PedigreePlugin = async ({ directory, worktree } = {}) => {
  const config = loadConfig(process.env);
  if (!config.enabled) return {};
  const core = createCore({
    config,
    projectRoot: worktree || directory,
    workingDirectory: directory,
    log: (...args) => {
      try {
        console.error(...args);
      } catch {
        /* logging must never break enforcement */
      }
    },
  });
  return {
    "tool.execute.before": (input, output) => core.beforeHook(input, output),
    "tool.execute.after": (input, output) => core.afterHook(input, output),
  };
};
