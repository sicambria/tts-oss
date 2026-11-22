#!/usr/bin/env node
/**
 * @description Claude Stop-hook gate: substantive dirty work must pass the configured verify contract
 * before the model may stop. Memory capture remains a separate, first Stop hook and is not gated here.
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot, git } from './lib/repo.mjs';
import { isExempt, isSubstantive } from './lib/branch-guard.mjs';

const VERIFY_SCRIPT = '.harness/scripts/verify.mjs';
const STOP_FAILURE_MESSAGE = 'tests/lint failing — fix before stopping';

function statusPaths(output) {
  return String(output || '')
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => line.slice(3).trim())
    .map((filePath) => filePath.includes(' -> ') ? filePath.split(' -> ').pop() : filePath);
}

/** Pure-ish predicate: only substantive dirty paths require the expensive verify run. */
export function shouldGate(root, cfg, gitFn = git) {
  const status = gitFn(['status', '--porcelain'], { cwd: root });
  if (status.code !== 0) return true; // inability to inspect state must not become a bypass
  return statusPaths(status.out).some((filePath) => isSubstantive(filePath, cfg) && !isExempt(filePath, cfg));
}

/** Run the configured verify contract through its canonical runner; any nonzero result is blocked. */
export function runStopVerify(root, spawn = spawnSync) {
  const result = spawn(process.execPath, [path.join(root, VERIFY_SCRIPT), '--phase', 'prepush'], {
    cwd: root,
    stdio: 'inherit',
  });
  return result?.status === 0 ? 0 : 2;
}

/** Thin CLI with dependency injection for deterministic unit tests. */
export function main(argv = [], opts = {}) {
  const root = opts.root ?? gitRoot();
  let cfg;
  try {
    cfg = opts.config ?? loadConfig(root);
  } catch {
    console.error(`${STOP_FAILURE_MESSAGE} (cannot load harness config)`);
    return 2;
  }
  if (cfg.guard?.stopVerify === false || !shouldGate(root, cfg, opts.gitFn)) return 0;
  const status = runStopVerify(root, opts.spawnFn);
  if (status !== 0) console.error(STOP_FAILURE_MESSAGE);
  return status;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
