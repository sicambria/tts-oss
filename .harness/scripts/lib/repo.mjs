#!/usr/bin/env node
/**
 * @description Git/repo helpers for payload scripts (run inside a target repo by the hooks).
 * All git access goes through here so the rest of the payload is testable and portable.
 */
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

function git(args, opts = {}) {
  const r = spawnSync('git', args, { encoding: 'utf8', ...opts });
  return { code: r.status ?? 1, out: (r.stdout || '').trim(), err: (r.stderr || '').trim() };
}

/** Absolute repo root, or process.cwd() if not in a git repo. */
export function repoRoot() {
  const r = git(['rev-parse', '--show-toplevel']);
  return r.code === 0 ? r.out : process.cwd();
}

/** Current branch name ('' if detached/unknown). */
export function currentBranch() {
  return git(['branch', '--show-current']).out;
}

/** Whether a merge is in progress (MERGE_HEAD present). */
export function mergeInProgress() {
  const gd = git(['rev-parse', '--git-dir']);
  if (gd.code !== 0) return false;
  return existsSync(path.join(gd.out, 'MERGE_HEAD'));
}

/** Staged file paths (added/copied/modified/renamed), repo-relative. */
export function stagedPaths() {
  const r = git(['diff', '--cached', '--name-only', '--diff-filter=ACMR']);
  return r.code === 0 ? r.out.split('\n').filter(Boolean) : [];
}

/** Number of registered worktrees (>=1). */
export function worktreeCount() {
  const r = git(['worktree', 'list', '--porcelain']);
  if (r.code !== 0) return 1;
  return (r.out.match(/^worktree /gm) || []).length || 1;
}

/** Ahead/behind counts vs an upstream ref (default origin/<branch>). */
export function aheadBehind(branch, remote = 'origin') {
  const b = branch || currentBranch();
  const r = git(['rev-list', '--left-right', '--count', `${remote}/${b}...${b}`]);
  if (r.code !== 0) return null;
  const [behind, ahead] = r.out.split(/\s+/).map((n) => parseInt(n, 10));
  return { ahead: ahead || 0, behind: behind || 0 };
}

/** Is a repo-relative path tracked by git? */
export function isTracked(rel) {
  return git(['ls-files', '--error-unmatch', rel]).code === 0;
}

/** Read a repo-relative file or null. */
export function readRepoFile(root, rel) {
  try { return readFileSync(path.join(root, rel), 'utf8'); } catch { return null; }
}

export { git };
