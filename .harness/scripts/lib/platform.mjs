#!/usr/bin/env node
/**
 * @description Shared cross-platform (Linux <-> Windows <-> macOS) helpers — `isWindows`/`isLinux`,
 * `findPython()`, and `runSeq()` — keeping platform branching in ONE place so it never leaks into
 * command definitions as POSIX-only (`sh -c`, env-prefix) or cmd-only (`set X=1&&`) idioms.
 * Ported verbatim from the changemappers reference harness (scripts/lib/platform.mjs).
 * @usage import { isWindows, findPython, runSeq } from '../lib/platform.mjs'
 */

import { spawnSync } from 'node:child_process';

export const isWindows = process.platform === 'win32';
export const isLinux = process.platform === 'linux';
export const isMac = process.platform === 'darwin';

/**
 * Resolve the Python interpreter name for this platform. Probe in preference order
 * and return the first that runs; fall back to the platform default so callers get
 * a clear "command not found" rather than an opaque throw here.
 * @returns {string}
 */
export function findPython() {
  const candidates = isWindows ? ['python', 'python3', 'py'] : ['python3', 'python'];
  for (const cmd of candidates) {
    const probe = spawnSync(cmd, ['--version'], { stdio: 'ignore', shell: isWindows });
    if (probe.status === 0) return cmd;
  }
  return isWindows ? 'python' : 'python3';
}

/**
 * Probe whether a command is runnable on this host (used by /doctor to check node/sh/gitleaks).
 * @param {string} cmd
 * @param {string[]} [args]
 * @returns {boolean}
 */
export function commandExists(cmd, args = ['--version']) {
  const probe = spawnSync(cmd, args, { stdio: 'ignore', shell: isWindows });
  return probe.status === 0;
}

/**
 * Run a list of shell command strings sequentially, fail-fast. Each step runs in its own
 * shell. Pass each step WITHOUT shell operators (`&&`, `;`, pipes) — sequencing is done here.
 * @param {string[]} steps
 * @returns {number} exit code of the first failing step, or 0 if all pass.
 */
export function runSeq(steps) {
  for (const step of steps) {
    if (!step || !step.trim()) continue;
    const r = spawnSync(step, { stdio: 'inherit', shell: true });
    if (r.error) {
      process.stderr.write(`[platform] failed to launch: ${step}\n${r.error.message}\n`);
      return 1;
    }
    if (r.status !== 0) return r.status == null ? 1 : r.status;
  }
  return 0;
}
