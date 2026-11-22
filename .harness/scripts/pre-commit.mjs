#!/usr/bin/env node
/**
 * @description pre-commit hook driver (Node — the .husky/-style sh idioms are forbidden by
 * verify-script-parity). Runs the consolidated branch-guard, then the core+adapter 'pre-commit'
 * gate chain. Fail-closed. For the single sanctioned install commit the installer writes a random
 * single-use nonce and sets KZ_BOOTSTRAP to it (bootstrapAuthorized), so the harness can commit
 * itself without the guard blocking it — while a bare/replayed KZ_BOOTSTRAP with no matching nonce
 * is rejected (never a silent bypass).
 */
import { loadConfigOrExit } from './lib/config.mjs';
import { repoRoot, currentBranch, stagedPaths, mergeInProgress } from './lib/repo.mjs';
import { isBlockedEdit } from './lib/branch-guard.mjs';
import { bootstrapAuthorized } from './lib/bootstrap-nonce.mjs';
import { runChain } from './gates/run-gates.mjs';
import { runChainedHooks } from './lib/chained-hooks.mjs';

const root = repoRoot();
const config = loadConfigOrExit(root, { label: 'pre-commit' });
const bootstrap = bootstrapAuthorized(root);

const guard = isBlockedEdit({
  branch: currentBranch(),
  paths: stagedPaths(),
  mergeInProgress: mergeInProgress(),
  bootstrap,
  config,
});
if (guard.blocked) {
  console.error(`✗ pre-commit BLOCKED: ${guard.reason}`);
  console.error(`  offending: ${guard.offending.join(', ')}`);
  console.error(`  → create a worktree and merge, or restrict this commit to exempt (docs) paths.`);
  process.exit(1);
}

const rc = runChain('pre-commit', root, config);
if (rc !== 0) process.exit(rc);

// Guest mode: kaizen runs INSIDE the existing manager's hook, which fires the repo's own controls
// natively — so there is nothing to chain (and chaining would re-enter this hook). Override mode:
// chain the repo's pre-existing pre-commit controls so kaizen never weakens them (no-op if none).
if (config.hooks?.mode === 'guest') process.exit(0);
process.exit(runChainedHooks('pre-commit', root, config, { args: process.argv.slice(2) }));
