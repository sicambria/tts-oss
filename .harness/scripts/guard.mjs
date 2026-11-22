#!/usr/bin/env node
/**
 * @description `guard start|status|reset` — the guard-session/GUARD-ID CLI. Mints/inspects/clears the
 * session that gates `config.guard.scaffolderCommands`. Same `main(argv)` / ✓/✗/! console convention as
 * doctor.mjs and verify-plan-evidence.mjs.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot } from './lib/repo.mjs';
import { mintSession, resetSession, guardStatus } from './lib/guard-session.mjs';

function printStatus(status) {
  if (!status.active && !status.guardId) {
    console.log('! no guard session — run `guard start` (or `kaizen guard start`)');
    return;
  }
  const state = status.stale ? 'STALE' : 'active';
  console.log(`${status.stale ? '!' : '✓'} guard session ${state}: ${status.guardId}`);
  console.log(`  minted: ${status.mintedAt}`);
  console.log(`  calls used: ${status.callsUsed} · remaining: ${status.callsRemaining}`);
}

export function main(argv) {
  const root = gitRoot();
  const config = loadConfig(root);
  const sub = argv[0] || 'status';

  switch (sub) {
    case 'start': {
      const session = mintSession(root);
      console.log(`✓ guard session started: ${session.guardId}`);
      return 0;
    }
    case 'status': {
      printStatus(guardStatus(root, config));
      return 0;
    }
    case 'reset': {
      resetSession(root);
      console.log('✓ guard session cleared');
      return 0;
    }
    default:
      console.error(`✗ unknown guard subcommand: ${sub} (use start|status|reset)`);
      return 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
