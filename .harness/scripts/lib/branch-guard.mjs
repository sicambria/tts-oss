#!/usr/bin/env node
/**
 * @description The SINGLE source of truth for "is this edit/commit blocked on the default branch?"
 * Consolidates the four divergent guards from the reference harness (pre-commit MERGE_HEAD form,
 * guard-branch.sh worktree-count form, check-edit-on-main.sh PreToolUse form, and the plan-evidence
 * mirror) into one pure predicate driven by config.branchGuard + config.defaultBranch.
 *
 * Canonical rule (MERGE_HEAD form — the reference's worktree-count form self-disables whenever any
 * worktree exists, a real defect): on the default branch, a change to any SUBSTANTIVE (non-exempt)
 * path is blocked UNLESS a merge is in progress (the sanctioned path to main). worktreeCount is
 * advisory only.
 */

function anyMatch(patterns, filePath) {
  return (patterns || []).some((p) => {
    try { return new RegExp(p).test(filePath); } catch { return false; }
  });
}

/**
 * Is a single path exempt (docs-like / trivial)?
 * @param {string} filePath repo-relative
 * @param {object} cfg
 */
export function isExempt(filePath, cfg) {
  return anyMatch(cfg.branchGuard?.exemptPaths, filePath);
}

/**
 * Is a single path substantive (code-like) — i.e. not exempt AND (matches substantive list OR the
 * substantive list is empty, meaning "anything non-exempt is substantive")?
 */
export function isSubstantive(filePath, cfg) {
  if (isExempt(filePath, cfg)) return false;
  const sub = cfg.branchGuard?.substantivePaths || [];
  return sub.length === 0 ? true : anyMatch(sub, filePath);
}

/**
 * The core guard predicate.
 * @param {object} params
 * @param {string} params.branch current branch
 * @param {string[]} params.paths changed/staged repo-relative paths
 * @param {boolean} params.mergeInProgress
 * @param {boolean} [params.bootstrap] sanctioned install-commit escape (allows .harness/** once)
 * @param {object} params.config
 * @returns {{blocked: boolean, reason: string, offending: string[]}}
 */
export function isBlockedEdit({ branch, paths, mergeInProgress, bootstrap = false, config }) {
  const def = config.defaultBranch || 'main';
  if (branch !== def) return { blocked: false, reason: `on non-default branch '${branch}'`, offending: [] };
  if (mergeInProgress) return { blocked: false, reason: 'merge in progress (sanctioned path to default branch)', offending: [] };

  // Every asset `kaizen init` stages for the ONE sanctioned bootstrap commit must be exempt here, or the
  // guard blocks kaizen's own install commit on a historied default branch. Keep in sync with the staged
  // set in cli/commands/init.mjs (agent overlays + .claude native payload + forge-CI backstops).
  const bootstrapExempt = (p) => bootstrap && (/^\.harness\//.test(p) || /^(AGENTS|CLAUDE)\.md$/.test(p) || /^\.gitignore$/.test(p) || /^\.(cursor|codex|github|claude|husky)\//.test(p) || /^opencode\.jsonc$/.test(p) || /^\.gitlab-ci\.yml$/.test(p) || /^bitbucket-pipelines\.yml$/.test(p));

  const offending = (paths || []).filter((p) => isSubstantive(p, config) && !bootstrapExempt(p));
  if (offending.length === 0) {
    return { blocked: false, reason: bootstrap ? 'bootstrap install commit (harness assets exempt once)' : 'only exempt paths changed', offending: [] };
  }
  return {
    blocked: true,
    reason: `substantive change on '${def}' without a merge: use a worktree + merge, or commit only exempt (docs) paths`,
    offending,
  };
}
