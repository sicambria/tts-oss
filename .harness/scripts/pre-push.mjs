#!/usr/bin/env node
/**
 * @description pre-push hook driver (Node). Order: (1) fail-closed /doctor — a push must not
 * proceed with broken enforcement; (2) the core+adapter 'pre-push' gate chain (learning-loop +
 * verify contract). Output is tee'd to a timestamped log for post-mortem diagnosability; RC is
 * captured fail-closed (empty/non-numeric → 1). Bypass via --no-verify is possible locally; the
 * un-bypassable guarantee is the CI backstop gated by branch protection.
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, existsSync, appendFileSync, readdirSync, unlinkSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { loadConfigOrExit } from './lib/config.mjs';
import { repoRoot } from './lib/repo.mjs';
import { runChain } from './gates/run-gates.mjs';
import { runChainedHooks } from './lib/chained-hooks.mjs';

const root = repoRoot();
const config = loadConfigOrExit(root, { label: 'pre-push' });

// Buffer git's stdin (the pushed-ref list) ONCE up front so it can be forwarded verbatim to any
// chained pre-push hook — a hook that filters by ref would misbehave without it. Guard against a TTY
// (manual invocation) so readFileSync(0) can't block; git runs hooks with stdin closed after the refs.
let prePushStdin = Buffer.alloc(0);
try { if (!process.stdin.isTTY) prePushStdin = readFileSync(0); } catch { /* no stdin — empty */ }
const logDir = path.join(root, config.hooks?.prePushLogDir || '.prepush-logs');

function log(line) {
  process.stdout.write(line + '\n');
  try {
    if (!existsSync(logDir)) mkdirSync(logDir, { recursive: true });
    appendFileSync(logFile, line + '\n');
  } catch { /* logging must never block */ }
}
const stamp = new Date(process.env.KZ_NOW_MS ? Number(process.env.KZ_NOW_MS) : Date.now())
  .toISOString().replace(/[:.]/g, '').replace('T', 'T').slice(0, 15);
const logFile = path.join(logDir, `${stamp}-${process.pid}.log`);

// Prune to newest 20 logs.
try {
  if (existsSync(logDir)) {
    const logs = readdirSync(logDir).filter((f) => f.endsWith('.log')).map((f) => path.join(logDir, f)).sort();
    for (const f of logs.slice(0, Math.max(0, logs.length - 20))) unlinkSync(f);
  }
} catch { /* best effort */ }

let rc = 0;

// (1) fail-closed doctor
log('→ pre-push: doctor (enforcement integrity)');
const doc = spawnSync('node', ['.harness/scripts/doctor.mjs', '--quiet'], { cwd: root, stdio: 'inherit' });
if (doc.status !== 0) { log('✗ pre-push: /doctor failed — enforcement is broken; push refused.'); process.exit(doc.status == null ? 1 : doc.status); }

// (2) pre-push gate chain
log('→ pre-push: gate chain');
rc = runChain('pre-push', root, config);

// (3) chained prior controls — override mode only. In guest mode kaizen runs INSIDE the manager's
//     pre-push, which fires the repo's own controls natively, so there is nothing to chain (and
//     chaining would re-enter this hook). Forward git's hook args + the buffered ref list otherwise.
if (rc === 0 && config.hooks?.mode !== 'guest') {
  log('→ pre-push: chained prior controls');
  rc = runChainedHooks('pre-push', root, config, { args: process.argv.slice(2), stdin: prePushStdin });
}

if (rc === 0) log(`[pre-push] OK — log ${path.relative(root, logFile)}`);
else log(`[pre-push] FAILED (rc ${rc}) — log ${path.relative(root, logFile)}`);
process.exit(Number.isInteger(rc) ? rc : 1);
