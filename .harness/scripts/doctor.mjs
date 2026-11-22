#!/usr/bin/env node
/**
 * @description Fail-closed health check. Exits non-zero when enforcement is broken — this is the
 * mechanism that makes the whole harness fail-closed (pre-push and CI both call it). WARNs are
 * visible but non-fatal. `--quiet` suppresses OK lines; `--fix` attempts safe repairs.
 *
 * Checks: hooks wired via core.hooksPath (present, executable, kaizen-managed); verify contract
 * filled; secret scanner status; memory committed in-repo (WARN-not-FAIL until the first .harness
 * commit exists — resolves the bootstrap deadlock); learning-loop scaffold; gate manifest present;
 * node/sh available; guard-session config sanity (FAILs closed — a malformed guard config or a
 * declared guarded command with no wired consumer is broken enforcement; an idle/absent *session*
 * stays OK; see check #9, roadmap Debt #4 closed).
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, accessSync, constants } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot, git, isTracked } from './lib/repo.mjs';
import { commandExists } from './lib/platform.mjs';
import { guardStatus, GUARD_CONSUMERS } from './lib/guard-session.mjs';
import { SCAFFOLD_COMMANDS } from './lib/scaffold-note.mjs';
import { checkCanary, readCanaryFiles } from './audits/verify-canary.mjs';
import { isNonceStale } from './lib/bootstrap-nonce.mjs';

function harnessEverCommitted() {
  return git(['log', '-1', '--format=%H', '--', '.harness']).out !== '';
}

export function runChecks(root, config) {
  const fails = [];
  const warns = [];
  const oks = [];

  // 1. hooks wired — topology-aware. OVERRIDE: kaizen owns core.hooksPath (.harness/hooks). GUEST:
  //    kaizen is wired INTO the existing manager's hook files, which keeps core.hooksPath — so here
  //    core.hooksPath NOT being .harness/hooks is correct, and we verify the guest block instead.
  const hp = git(['config', '--get', 'core.hooksPath']).out;
  if (config.hooks?.mode === 'guest') {
    const dir = '.husky';
    for (const h of ['pre-commit', 'pre-push']) {
      const hf = path.join(root, dir, h);
      if (!existsSync(hf)) { fails.push(`guest hook missing: ${dir}/${h} — kaizen not wired`); continue; }
      const c = readFileSync(hf, 'utf8');
      if (!c.includes('kaizen-guest')) fails.push(`guest block missing in ${dir}/${h} — kaizen not wired (run kaizen init)`);
      else if (!c.includes(`.harness/scripts/${h}.mjs`)) fails.push(`guest block in ${dir}/${h} does not invoke .harness/scripts/${h}.mjs`);
    }
    for (const h of ['pre-commit', 'pre-push']) {
      if (!existsSync(path.join(root, '.harness', 'scripts', `${h}.mjs`))) fails.push(`driver missing: .harness/scripts/${h}.mjs`);
    }
    if (hp === '.harness/hooks') fails.push(`guest mode but core.hooksPath is '.harness/hooks' — the existing manager should own it (stale override wiring)`);
    if (fails.length === 0) oks.push(`hooks wired via guest mode (into ${dir}/; core.hooksPath kept by the existing manager)`);
  } else if (hp !== '.harness/hooks') {
    fails.push(`git core.hooksPath is '${hp || '(unset)'}', expected '.harness/hooks' — hooks not wired`);
  } else {
    for (const h of ['pre-commit', 'pre-push']) {
      const hf = path.join(root, '.harness', 'hooks', h);
      if (!existsSync(hf)) { fails.push(`hook missing: .harness/hooks/${h}`); continue; }
      try { accessSync(hf, constants.X_OK); } catch { fails.push(`hook not executable: .harness/hooks/${h}`); }
      if (!readFileSync(hf, 'utf8').includes('kaizen-managed-hook')) fails.push(`hook not kaizen-managed: .harness/hooks/${h} (a foreign hook occupies this path)`);
    }
    if (fails.length === 0) oks.push('hooks wired via core.hooksPath');
  }

  // 2. runtime present
  if (!commandExists('node')) fails.push('node not found on PATH (payload scripts require it)');
  else oks.push('node available');

  // 2b. POSIX `sh` present (WU-4). The git hook shims are `#!/bin/sh` and the chained-hook runner
  //     hard-codes `cmd='sh'`; on a host without a POSIX shell (Windows without Git-Bash) a commit
  //     fail-closes with an opaque spawn error. WARN (not FAIL) — don't brick a doctor run on the
  //     check itself; diagnose the fix so the opaque failure becomes actionable.
  if (!commandExists('sh', ['-c', 'true'])) warns.push('POSIX `sh` not found on PATH — the git hook shims (#!/bin/sh) and the chained-hook runner (cmd=\'sh\') need it; on Windows install Git-Bash or run under WSL, else commits fail-close with an opaque spawn error');
  else oks.push('sh available');

  // 3. verify contract filled (required: test/lint/build non-empty or explicit "N/A")
  const v = config.verify || {};
  const filled = (x) => x && String(x).trim(); // non-empty; explicit "N/A" counts as intentionally filled
  const unfilled = ['test', 'lint', 'build'].filter((k) => !filled(v[k]));
  if (unfilled.length) fails.push(`verify contract unfilled: ${unfilled.join(', ')} (edit .harness/config.json → verify; use "N/A" if a step genuinely does not apply)`);
  else oks.push('verify contract filled');

  // 4. secret scanner
  const scanner = config.security?.secretScanner || 'none';
  if (scanner === 'gitleaks' && !commandExists('gitleaks', ['version'])) fails.push('secret scanner is gitleaks but gitleaks is not installed');
  else if (scanner === 'none') warns.push('secret scanning on pure-Node FALLBACK (gitleaks not found at install) — the fallback ruleset enforces on staged diffs; install gitleaks + `kaizen doctor --fix` for full-depth history scanning');
  else oks.push(`secret scanner: ${scanner}`);

  // 5. memory committed in-repo (bootstrap-aware)
  const memRel = '.harness/memory/memory.md';
  if (!existsSync(path.join(root, memRel))) fails.push('memory file missing: .harness/memory/memory.md');
  else if (!isTracked(memRel)) {
    if (harnessEverCommitted()) fails.push('memory not committed in-repo: .harness/memory/memory.md (git add + commit it)');
    else warns.push('memory not yet committed (fresh install) — will be committed by the bootstrap commit');
  } else oks.push('memory committed in-repo');

  // 6. gate manifest present
  if (!existsSync(path.join(root, '.harness', 'gates', 'core.gates.json'))) fails.push('missing gate manifest: .harness/gates/core.gates.json');
  else oks.push('gate manifest present');

  // 7. learning-loop scaffold (WARN if absent/empty)
  const errorsDir = path.join(root, config.docs?.learningLoop?.errorsDir || 'docs/errors');
  if (!existsSync(errorsDir)) warns.push(`learning-loop dir absent: ${path.relative(root, errorsDir)} (created on first incident)`);
  else oks.push('learning-loop scaffold present');

  // 8. CI backstop (WARN — branch protection can't be verified locally)
  if (!existsSync(path.join(root, '.github', 'workflows', 'kaizen-gate.yml'))) warns.push('CI backstop workflow absent (.github/workflows/kaizen-gate.yml) — fail-closed is local-only until added + branch protection enabled');

  // 9. guard-session config sanity + consumer wiring. FAIL-closed now that a real requireGuard() consumer
  //    exists (`next:execute`, roadmap Debt #4 closed): a malformed guard config or a guarded command with
  //    no wired consumer is broken enforcement, so it FAILs. A missing/idle *session* stays OK — idle is a
  //    normal state, not broken enforcement.
  const g = config.guard || {};
  if (!(Number.isFinite(g.maxCalls) && g.maxCalls > 0)) fails.push(`guard.maxCalls is not a positive number: ${JSON.stringify(g.maxCalls)}`);
  if (!(Number.isFinite(g.staleMinutes) && g.staleMinutes > 0)) fails.push(`guard.staleMinutes is not a positive number: ${JSON.stringify(g.staleMinutes)}`);
  if (!Array.isArray(g.scaffolderCommands)) fails.push(`guard.scaffolderCommands is not an array: ${JSON.stringify(g.scaffolderCommands)}`);
  // Each declared guarded command must map to a wired consumer (a note-scaffolder in SCAFFOLD_COMMANDS or a
  // non-scaffolder consumer in GUARD_CONSUMERS), else the guard gates a command that nothing implements.
  for (const cmd of Array.isArray(g.scaffolderCommands) ? g.scaffolderCommands : []) {
    if (!(cmd in SCAFFOLD_COMMANDS) && !GUARD_CONSUMERS.has(cmd)) fails.push(`guard.scaffolderCommands lists '${cmd}' but no consumer is wired for it (see scripts/lib/scaffold-note.mjs SCAFFOLD_COMMANDS or scripts/lib/guard-session.mjs GUARD_CONSUMERS)`);
  }
  if (Number.isFinite(g.maxCalls) && g.maxCalls > 0 && Number.isFinite(g.staleMinutes) && g.staleMinutes > 0 && Array.isArray(g.scaffolderCommands)) {
    const status = guardStatus(root, config);
    oks.push(status.active ? `guard session active (${status.callsRemaining} call(s) remaining)` : 'guard-session config sane (no active session)');
  }

  // 10. contract-read canary integrity (L4). Drift — a marker added/removed out of sync with the
  //     AGENTS.md protocol section — fails closed once the harness is committed. On a fresh pre-bootstrap
  //     tree the markers ship with `init`, so it only WARNs (mirrors the memory-not-yet-committed case).
  const canary = checkCanary(readCanaryFiles(root));
  if (canary.ok) oks.push('contract-read canary intact');
  else if (harnessEverCommitted()) for (const e of canary.errors) fails.push(`canary: ${e}`);
  else warns.push('contract-read canary not yet in place (fresh install — ships via init)');

  // 11. chained controls present on disk — never silently orphan a gate (AGENTS.md "never silently
  //     orphan a gate"). OVERRIDE installs chain the repo's pre-existing hooks in config.hooks.chained
  //     so they keep firing after kaizen takes core.hooksPath. If the user later DELETES a chained hook
  //     file, runChainedHooks only warns to stderr and continues (lib/chained-hooks.mjs) — the relied-on
  //     control silently stops enforcing. Resolve each path the SAME way the runtime does and FAIL (not
  //     warn) on a missing one: a control the repo relied on that vanished must turn the fail-closed
  //     doctor red until it is restored or retired via a logged decision.
  for (const [hookName, list] of Object.entries(config.hooks?.chained || {})) {
    if (!Array.isArray(list) || list.length === 0) continue;
    let present = 0;
    for (const rel of list) {
      const abs = path.isAbsolute(rel) ? rel : path.join(root, rel); // == lib/chained-hooks.mjs resolution
      if (existsSync(abs)) { present++; continue; }
      fails.push(`orphaned chained control: ${hookName} → '${rel}' no longer exists on disk — a control this repo relied on is gone and is not firing. Restore the file, or remove it from .harness/config.json → hooks.chained.${hookName} via a logged decision (.harness/archive/decisions/).`);
    }
    if (present === list.length) oks.push(`chained ${hookName} control(s) present (${present})`);
  }

  // 12. stale bootstrap nonce (HARDEN-7 / WI-8). The installer clears .harness/state/bootstrap-nonce in a
  //     `finally`, which a SIGKILL/power-loss SKIPS — leaving a nonce on disk. The TTL in bootstrap-nonce.mjs
  //     already REJECTS an expired nonce (bootstrapAuthorized returns false), so a leftover is an inert token,
  //     not an active bypass → WARN is the honest severity (not FAIL). A fresh within-TTL nonce exists only
  //     mid-install and is NOT flagged.
  if (isNonceStale(root)) warns.push('stale bootstrap nonce present: .harness/state/bootstrap-nonce is a leftover from an abnormally-terminated install (older than the TTL / legacy format). It can no longer authorize a bootstrap (the TTL rejects it) — an inert expired token. Delete it: rm -f .harness/state/bootstrap-nonce');

  // 13. harness version stamp (HARDEN-9 / WI-9) — DEFENSIVE mirror only. doctor runs from the committed
  //     in-repo .harness/scripts and has NO line of sight to the npm CLI's package.json, so it CANNOT
  //     compare against the current CLI version — that authoritative drift compare lives in
  //     `kaizen init --check` (which runs the upgraded CLI and holds its version). Here we only surface
  //     the stamp when present (a health signal); a MISSING stamp is silently skipped, never a WARN, so
  //     a not-yet-re-init'd repo is not spammed on every pre-push. Never throws.
  if (typeof config.harnessVersion === 'string' && config.harnessVersion) oks.push(`harness version stamped (v${config.harnessVersion}); run \`kaizen init --check\` to compare against the CLI`);

  return { fails, warns, oks };
}

export function main(argv) {
  const quiet = argv.includes('--quiet');
  const root = gitRoot();
  const config = loadConfig(root);
  const { fails, warns, oks } = runChecks(root, config);

  if (!quiet) for (const o of oks) console.log(`✓ ${o}`);
  for (const w of warns) console.error(`! ${w}`);
  for (const f of fails) console.error(`✗ ${f}`);

  if (fails.length) { console.error(`\n✗ doctor: ${fails.length} failure(s) — enforcement is not intact.`); return 1; }
  if (!quiet) console.log(`\n✓ doctor: enforcement intact${warns.length ? ` (${warns.length} warning(s))` : ''}.`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
