#!/usr/bin/env node
/**
 * @description Fail-closed chaining of a repo's pre-existing git hooks. When kaizen takes over
 * core.hooksPath, whatever fired before (husky / pre-commit framework / hand-written .git/hooks /
 * a custom hooksPath) would silently stop. kaizen's drivers call runChainedHooks AFTER their own
 * gates pass, so every prior control keeps running and keeps blocking — installing the harness
 * never weakens a repo's existing controls, it only adds to them. Purely additive: a config with
 * no `hooks.chained` is a no-op and behaves byte-for-byte as before.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { bootstrapAuthorized } from './bootstrap-nonce.mjs';

const KZ_MARKER = 'kaizen-managed-hook';

/** True if `abs` is one of kaizen's own hook shims — never chain ourselves (would loop). */
function isKaizenShim(abs) {
  if (abs.includes(`${path.sep}.harness${path.sep}hooks${path.sep}`)) return true;
  try { return readFileSync(abs, 'utf8').includes(KZ_MARKER); } catch { return false; }
}

/**
 * Run every prior hook recorded under config.hooks.chained[hookName], in order, fail-closed.
 * @param {string} hookName 'pre-commit' | 'pre-push'
 * @param {string} root repo root
 * @param {object} config loaded .harness/config.json
 * @param {{args?:string[], stdin?:Buffer|string}} [io] git's hook args + stdin (ref list for pre-push)
 * @returns {number} 0 if all chained hooks pass (or none/skip); the first non-zero exit code otherwise.
 */
export function runChainedHooks(hookName, root, config, io = {}) {
  // The single sanctioned install commit must NOT run the user's hooks against kaizen's own staged
  // files — mirrors the branch-guard bootstrap exemption. Authorized only when KZ_BOOTSTRAP matches
  // the installer's single-use nonce (bootstrap-nonce.mjs); a bare/replayed env var is rejected and
  // the chained controls run normally. Normal commits run the chained hooks.
  if (bootstrapAuthorized(root)) return 0;
  const list = config?.hooks?.chained?.[hookName];
  if (!Array.isArray(list) || list.length === 0) return 0;
  const { args = [], stdin } = io;
  for (const rel of list) {
    const abs = path.isAbsolute(rel) ? rel : path.join(root, rel);
    if (!existsSync(abs)) {
      // A recorded control the user later removed: warn loudly, don't brick their commit. Silently
      // failing closed on a hook they deleted would itself be a surprise; a missing script isn't one.
      console.error(`⚠ chained ${hookName}: '${rel}' no longer exists — skipping (that control is not firing).`);
      continue;
    }
    if (isKaizenShim(abs)) continue; // never chain ourselves
    // Run it directly if the execute bit is set, else via `sh` (POSIX hook scripts often aren't +x).
    let cmd, argv;
    try {
      const executable = (statSync(abs).mode & 0o111) !== 0;
      if (executable) { cmd = abs; argv = args; } else { cmd = 'sh'; argv = [abs, ...args]; }
    } catch { cmd = 'sh'; argv = [abs, ...args]; }
    console.log(`→ ${hookName}: chained control ${rel}`);
    const r = spawnSync(cmd, argv, {
      cwd: root,
      stdio: stdin == null ? 'inherit' : ['pipe', 'inherit', 'inherit'],
      input: stdin == null ? undefined : stdin,
    });
    const code = r.status == null ? 1 : r.status;
    if (code !== 0) {
      console.error(`✗ chained ${hookName} control '${rel}' failed (rc ${code}) — ${hookName} refused (never-weaken).`);
      return code;
    }
  }
  return 0;
}
