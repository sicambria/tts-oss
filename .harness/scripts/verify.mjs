#!/usr/bin/env node
/**
 * @description The verify-contract runner (the portability keystone). Runs the stack commands
 * declared in config.verify behind a stable interface, so the harness owns orchestration while the
 * project/adapter fills the commands. Empty commands are treated per honest-abstain: a REQUIRED
 * field left empty → human_needed (fail closed), an optional field (e2e/healthcheck) left empty →
 * skipped. Bad command exit → BLOCK.
 *
 * Usage: verify.mjs [--phase prepush|full] [--allow-abstain]
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot } from './lib/repo.mjs';

const REQUIRED = ['test', 'lint', 'build'];
const OPTIONAL = ['e2e', 'healthcheck'];

export function main(argv) {
  const root = gitRoot();
  const cfg = loadConfig(root);
  const v = cfg.verify || {};
  const phase = argv.includes('--phase') ? argv[argv.indexOf('--phase') + 1] : 'prepush';
  const order = phase === 'full' ? [...REQUIRED, ...OPTIONAL] : REQUIRED;

  let abstained = 0;
  for (const key of order) {
    const cmd = (v[key] || '').trim();
    const optional = OPTIONAL.includes(key);
    if (/^N\/A\b/i.test(cmd)) { console.log(`  ~ verify:${key} N/A (declared not applicable)`); continue; }
    if (!cmd) {
      if (optional) { console.log(`  ~ verify:${key} skipped (no command; explicitly optional)`); continue; }
      // honest-abstain: cannot mechanically confirm — do NOT silently pass.
      console.error(`✗ verify:${key} = human_needed — required verify command is unfilled. Fill config.verify.${key}.`);
      abstained++;
      continue;
    }
    console.log(`→ verify:${key} → ${cmd}`);
    const r = spawnSync(cmd, { cwd: root, stdio: 'inherit', shell: true });
    if (r.status !== 0) { console.error(`✗ verify:${key} failed (exit ${r.status ?? 'signal'})`); return 1; }
  }
  if (abstained > 0) {
    console.error(`✗ verify: ${abstained} required check(s) abstained (human_needed) — fail closed.`);
    return 1;
  }
  console.log('✓ verify: contract satisfied');
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
