#!/usr/bin/env node
/**
 * @description Plan lifecycle move helper (wave3-B). RCA-born: a `git mv` stages only the
 * rename while reference-cascade rewrites land UNSTAGED, so a later pathspec commit silently
 * drops them. This module pairs the move with its cascade and guards both ends with
 * `assertNoUnstagedResidue` — a post-mutation invariant for any scripted git rewrite.
 *
 * Pure core (`parseResidue`, `unstagedResidue`, `assertNoUnstagedResidue`, `planMove` over an
 * injected git runner) + a thin CLI. No shell — git is spawned with an argv array only — and
 * every path is contained inside the repo root before it is touched.
 *
 *   node plan-move.mjs --from docs/plans/foo.md --to docs/plans/done/foo.md \
 *     --ref docs/plans/worktree-current-state.md:docs/plans/foo.md:docs/plans/done/foo.md
 */
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

/** Spawn git with an argv array (never a shell string) in `cwd`. Output is right-trimmed
 * only: `git status --porcelain` encodes state in LEADING columns (` M` = worktree-only),
 * so a full trim would silently erase residue. */
export function runGit(args, cwd) {
  const r = spawnSync('git', args, { encoding: 'utf8', cwd });
  return { code: r.status ?? 1, out: (r.stdout || '').trimEnd(), err: (r.stderr || '').trim() };
}

/**
 * Parse `git status --porcelain` output into unstaged-residue entries.
 * Residue = the worktree differs from the index: the Y (worktree) column of the XY
 * status code is anything but space, which covers modified (` M`), deleted (` D`),
 * and untracked (`??`) paths. Staged-only entries (`M `, `R `, `A `) are NOT residue —
 * staging is exactly where a scripted rewrite must leave its outputs.
 * @param {string} porcelain raw `git status --porcelain` stdout
 * @returns {string[]} repo-relative paths with unstaged changes
 */
export function parseResidue(porcelain) {
  const out = [];
  for (const line of String(porcelain || '').split('\n')) {
    if (!line) continue;
    const x = line[0];
    const y = line[1];
    if (x === '?' && y === '?') {
      out.push(line.slice(3));
    } else if (y !== ' ' && y !== undefined) {
      out.push(line.slice(3));
    }
  }
  return out;
}

/**
 * List unstaged-residue paths in `root`. Pure over the injected runner.
 * @param {string} root repo root (cwd for git)
 * @param {Function} run git runner `(args, cwd) -> {code,out,err}`
 */
export function unstagedResidue(root, run = runGit) {
  const r = run(['status', '--porcelain'], root);
  if (r.code !== 0) throw new Error(`plan-move: git status failed: ${r.err || `exit ${r.code}`}`);
  return parseResidue(r.out);
}

/**
 * Post-mutation invariant: fail closed when any unstaged residue remains.
 * @returns {true} when the tree is clean
 * @throws {Error} listing every residue path
 */
export function assertNoUnstagedResidue(root, run = runGit) {
  const residue = unstagedResidue(root, run);
  if (residue.length > 0) {
    throw new Error(`plan-move: unstaged residue — stage or discard before proceeding: ${residue.join(', ')}`);
  }
  return true;
}

/** Reject absolute paths and `..` escapes so cascade targets stay inside the repo root. */
export function assertInsideRoot(root, rel) {
  if (typeof rel !== 'string' || rel.length === 0) throw new Error('plan-move: empty path');
  const abs = path.resolve(root, rel);
  const base = path.resolve(root) + path.sep;
  if (abs !== path.resolve(root) && !abs.startsWith(base)) {
    throw new Error(`plan-move: path escapes repo root: ${rel}`);
  }
  return abs;
}

/**
 * Move a plan file and cascade its reference rewrites, all staged.
 * Pre-condition: the tree is clean (refuses on a dirty tree so the move never mixes
 * with unrelated work). Post-condition: `assertNoUnstagedResidue` — every output of
 * this rewrite is staged, so a later pathspec commit cannot silently drop the cascade.
 * @param {{root:string, from:string, to:string, cascade?:Array<{file:string,oldRef:string,newRef:string}>, run?:Function, read?:Function, write?:Function}} opts
 * @returns {{from:string, to:string, staged:string[]}}
 */
export function planMove({ root, from, to, cascade = [], run = runGit, read = readFileSync, write = writeFileSync }) {
  if (!root) throw new Error('plan-move: root is required');
  assertInsideRoot(root, from);
  assertInsideRoot(root, to);
  assertNoUnstagedResidue(root, run);

  mkdirSync(path.dirname(assertInsideRoot(root, to)), { recursive: true });
  const mv = run(['mv', from, to], root);
  if (mv.code !== 0) throw new Error(`plan-move: git mv ${from} -> ${to} failed: ${mv.err || `exit ${mv.code}`}`);

  const staged = [to];
  for (const { file, oldRef, newRef } of cascade) {
    assertInsideRoot(root, file);
    if (!oldRef) throw new Error(`plan-move: cascade entry for ${file} has an empty oldRef`);
    const abs = path.join(root, file);
    const content = read(abs, 'utf8');
    if (!content.includes(oldRef)) {
      throw new Error(`plan-move: reference not found in ${file}: ${oldRef}`);
    }
    write(abs, content.split(oldRef).join(newRef));
    const add = run(['add', file], root);
    if (add.code !== 0) throw new Error(`plan-move: git add ${file} failed: ${add.err || `exit ${add.code}`}`);
    staged.push(file);
  }

  assertNoUnstagedResidue(root, run);
  return { from, to, staged };
}

/** CLI: --from <p> --to <p> [--ref file:old:new ...] (repeatable). */
export function main(argv = []) {
  const opt = (name) => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 ? argv[i + 1] : null;
  };
  const from = opt('from');
  const to = opt('to');
  if (!from || !to) {
    console.error('usage: plan-move.mjs --from <path> --to <path> [--ref file:old:new ...]');
    return 2;
  }
  const cascade = argv
    .flatMap((a, i) => (a === '--ref' ? [argv[i + 1]] : []))
    .filter(Boolean)
    .map((spec) => {
      const parts = spec.split(':');
      if (parts.length < 3) throw new Error(`plan-move: bad --ref spec (want file:old:new): ${spec}`);
      const [file, oldRef, ...rest] = parts;
      return { file, oldRef, newRef: rest.join(':') };
    });
  const root = gitRoot();
  const res = planMove({ root, from, to, cascade });
  console.log(`✓ plan-move: ${res.from} -> ${res.to} (+${res.staged.length - 1} cascade file(s), all staged)`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exit(main(process.argv.slice(2)));
  } catch (err) {
    console.error(`✗ ${err.message}`);
    process.exit(1);
  }
}
