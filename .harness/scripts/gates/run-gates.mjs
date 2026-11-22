#!/usr/bin/env node
/**
 * @description Fail-fast, fail-closed gate-chain runner. `run-gates.mjs <chain>` resolves the
 * merged core+adapter gate list for the chain and runs each in order; the first non-zero exit stops
 * the chain and propagates. A missing gate script is a FAILURE (fail-closed), not a skip.
 */
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { resolveChain } from './registry.mjs';

export function runChain(chain, root, config) {
  const gates = resolveChain(root, config, chain);
  if (gates.length === 0) { console.log(`(no gates in chain '${chain}')`); return 0; }
  for (const g of gates) {
    // Verify the gate's target script exists (fail-closed on a broken registry).
    const scriptArg = g.run.find((a) => a.endsWith('.mjs') || a.endsWith('.js'));
    if (scriptArg && !existsSync(path.join(root, scriptArg))) {
      console.error(`✗ gate '${g.id}' (${g.source}): missing script ${scriptArg} — fail closed`);
      return 1;
    }
    const [cmd, ...args] = g.run;
    const r = spawnSync(cmd, args, { cwd: root, stdio: 'inherit' });
    if (r.status !== 0) {
      console.error(`✗ gate '${g.id}' (${g.source}) failed — chain '${chain}' halted`);
      return r.status == null ? 1 : r.status;
    }
  }
  console.log(`✓ chain '${chain}': ${gates.length} gate(s) passed`);
  return 0;
}

export function main(argv) {
  const chain = argv[0];
  if (!chain) { console.error('usage: run-gates.mjs <chain>'); return 2; }
  const root = gitRoot();
  const config = loadConfig(root);
  return runChain(chain, root, config);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
