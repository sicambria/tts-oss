#!/usr/bin/env node
/**
 * @description Cross-AI peer-review routing (P2-16, src: GSD). A config-driven `/cross-review` runner:
 * it fans the working diff out to N configured external reviewers (Gemini / Codex / CodeRabbit CLIs, or
 * ANY command that reads a unified diff on stdin and prints findings on stdout), then ranks each
 * reviewer's raw output by **file-grounded evidence** — how many of the `path:line` citations in the
 * output actually resolve against the working tree.
 *
 * Honest-abstain per the harness's fail-closed philosophy (mirrors `ops/deploy.mjs`'s `human_needed`
 * shape): NO configured providers, or every configured provider skipped for a missing key-env,
 * ABSTAINS (exit 1, an error printed, an `abstain` event logged) — a review that ran nothing is not a
 * pass. An EMPTY diff is a determinate "nothing to review" (exit 0, `status:noop`), not an abstain.
 *
 * ADVISORY, NOT A GATE. This is an on-demand command; it is deliberately NOT wired into pre-commit.
 * Wiring AI-review-only into the blocking path is a documented anti-pattern ("silent-pass / AI-review-
 * only verification with no test execution"). Citation grounding is advisory *ranking*, never a verdict.
 *
 * SECURITY: the net-new surface vs `/deploy` is spawning external reviewer CLIs. The provider `cmd` is
 * operator-authored committed config (same trust model as `config.deploy.cmd`). The diff content and
 * filenames are NEVER interpolated into the shell command — the diff is passed to the reviewer process
 * on STDIN via `spawnSync({ input })`. (`defaultSpawn` therefore PIPES stdio and CAPTURES stdout; it
 * must NOT copy deploy's `stdio:'inherit'`, under which `input` is ignored and `stdout` is null.)
 *
 * Pure-ish core `runReview(root, cfg, { spawn, diffProvider, env })` — all three collaborators are
 * injectable so the full state machine is unit-testable without a real process, network, or env
 * mutation. Mirrors the injectable-collaborator DI seam of every other `ops/*.mjs` (`deploy.mjs:118`).
 *
 * Usage: node review.mjs
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { logEvent } from './events.mjs';

/**
 * Default `spawn` collaborator. CRITICAL: pipes stdio (default) and captures `stdout`, and feeds
 * `input` to the child's stdin — the OPPOSITE wiring from `deploy.mjs`'s `stdio:'inherit'` spawn, under
 * which `input` is ignored and `stdout` is null. `shell:true` runs the operator-authored `cmd` string;
 * the untrusted diff reaches the child only via `input` (stdin), never the command string.
 * @param {string} command operator-authored shell command
 * @param {{input?: string}} [opts]
 * @returns {{status: number, stdout: string}}
 */
function defaultSpawn(command, opts = {}) {
  const r = spawnSync(command, { input: opts.input, cwd: opts.cwd, encoding: 'utf8', shell: true, maxBuffer: 32 * 1024 * 1024 });
  return { status: r.status ?? (r.signal ? 1 : 0), stdout: r.stdout || '' };
}

/**
 * Gather the working diff to review: everything on this branch since it diverged from `defaultBranch`
 * (`git diff --merge-base <defaultBranch>`), falling back to `git diff HEAD` when there is no merge base
 * (detached HEAD, unrelated history, or running ON the default branch). Returns the diff string ('' ⇒
 * nothing to review). Pure-ish: the `spawn` collaborator is injected.
 * @param {string} root repo root
 * @param {string} defaultBranch e.g. 'main'
 * @param {Function} spawn injected spawn `(cmd) => {status, stdout}`
 * @returns {string}
 */
export function gatherDiff(root, defaultBranch, spawn) {
  const branch = (defaultBranch || 'main').replace(/[^\w./-]/g, ''); // defensive: config value, but sanitize anyway
  // `root` is passed as spawn `cwd` (never interpolated into the shell string) — a maliciously *named*
  // repo dir cannot break out of the command, unlike an unsanitized `git -C "${root}"`.
  const primary = spawn(`git diff --merge-base ${branch}`, { cwd: root });
  if (primary.status === 0 && (primary.stdout || '').trim()) return primary.stdout;
  if (primary.status === 0) return ''; // merge-base worked, genuinely no diff
  const fallback = spawn(`git diff HEAD`, { cwd: root });
  return fallback.status === 0 ? fallback.stdout || '' : '';
}

/**
 * Pull `path:line` citation tokens out of arbitrary reviewer output. Conservative regex — a token is a
 * dotted filename (with an extension) followed by `:<digits>`. Pure, no I/O.
 * @param {string} text a reviewer's raw stdout
 * @returns {Array<{path: string, line: number}>}
 */
export function extractCitations(text) {
  const out = [];
  const re = /([A-Za-z0-9._\-/]+\.[A-Za-z0-9]+):(\d+)/g;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) {
    out.push({ path: m[1], line: Number(m[2]) });
  }
  return out;
}

/**
 * Weight one reviewer's opaque output by file-grounded evidence. Does NOT parse prose into structured
 * findings (reviewer formats vary wildly — a per-provider parser would be brittle over-engineering).
 * Instead it extracts every `path:line` citation and checks each against the working tree (file exists
 * AND has at least that many lines — the same resolve check as `verify-plan-evidence.mjs`). A review
 * whose citations resolve outranks an ungrounded wall of prose (which cites nothing ⇒ ratio 0).
 * @param {string} root repo root
 * @param {{name: string, raw: string}} review
 * @returns {{name, raw, citations: Array<{path,line,resolves}>, groundedCount, totalCitations, groundingRatio}}
 */
export function weightReview(root, { name, raw }) {
  const rootAbs = path.resolve(root);
  const citations = extractCitations(raw).map((c) => {
    let resolves = false;
    const abs = path.resolve(root, c.path);
    // Proper containment: `abs` is inside root only if it IS root or sits under `root + sep`. A bare
    // `startsWith(rootAbs)` is unsound — a sibling like `<root>-backup` shares the prefix and would
    // let a malicious reviewer falsely "ground" a citation against a file OUTSIDE the repo.
    const contained = abs === rootAbs || abs.startsWith(rootAbs + path.sep);
    if (contained && existsSync(abs)) {
      try {
        const lines = readFileSync(abs, 'utf8').split('\n').length;
        resolves = c.line >= 1 && c.line <= lines;
      } catch {
        resolves = false;
      }
    }
    return { ...c, resolves };
  });
  const groundedCount = citations.filter((c) => c.resolves).length;
  const totalCitations = citations.length;
  const groundingRatio = totalCitations ? groundedCount / totalCitations : 0;
  return { name, raw, citations, groundedCount, totalCitations, groundingRatio };
}

/**
 * Run the cross-AI review state machine. Never throws.
 * @param {string} root repo root (absolute)
 * @param {object} cfg loaded harness config
 * @param {{spawn?: Function, diffProvider?: Function, env?: object}} [opts]
 * @returns {number} process exit code (0 = reviewed or nothing-to-review; 1 = abstain)
 */
export function runReview(root, cfg, opts = {}) {
  const spawn = opts.spawn || defaultSpawn;
  const env = opts.env || process.env;
  const r = (cfg && cfg.review) || {};
  const providers = Array.isArray(r.providers) ? r.providers.filter((p) => p && p.name && p.cmd) : [];

  // 1. Abstain — no usable providers configured. Honest-abstain, never silent-pass.
  if (providers.length === 0) {
    logEvent(root, { type: 'review', status: 'abstain', reason: 'config.review.providers is empty' });
    console.error('✗ cross-review: human_needed — no reviewers in config.review.providers. Add { name, cmd, keyEnv } entries to enable /cross-review.');
    return 1;
  }

  // 2. Gather the diff. Empty ⇒ determinate "nothing to review" (exit 0), NOT an abstain.
  const defaultBranch = (cfg && cfg.defaultBranch) || 'main';
  const diffProvider = opts.diffProvider || ((rt) => gatherDiff(rt, defaultBranch, spawn));
  const diff = diffProvider(root) || '';
  if (!diff.trim()) {
    logEvent(root, { type: 'review', status: 'noop', reason: 'empty diff' });
    console.log('✓ cross-review: nothing to review (empty diff).');
    return 0;
  }

  // 3. Fan out to each provider; a missing key-env skips (abstains) THAT provider — never a silent pass.
  const results = [];
  let ranAny = false;
  for (const p of providers) {
    if (p.keyEnv && !((env[p.keyEnv] || '').trim())) {
      logEvent(root, { type: 'review', provider: p.name, status: 'abstain', reason: `${p.keyEnv} not set` });
      console.error(`  ~ ${p.name}: skipped — ${p.keyEnv} not set.`);
      continue;
    }
    ranAny = true;
    const res = spawn(p.cmd, { input: diff });
    const weighted = weightReview(root, { name: p.name, raw: res.stdout || '' });
    logEvent(root, {
      type: 'review',
      provider: p.name,
      status: res.status === 0 ? 'ok' : 'error',
      exit: res.status,
      groundedCount: weighted.groundedCount,
      totalCitations: weighted.totalCitations,
    });
    results.push({ ...weighted, exit: res.status });
  }

  // 4. Every provider was key-gated ⇒ nothing actually ran ⇒ overall abstain.
  if (!ranAny) {
    logEvent(root, { type: 'review', status: 'abstain', reason: 'all providers missing key-env' });
    console.error('✗ cross-review: human_needed — every configured reviewer was skipped (no key-env set). Set a provider key to enable a real review.');
    return 1;
  }

  // 5. Report, most-grounded reviewer first (stable sort by grounding ratio desc).
  results.sort((a, b) => b.groundingRatio - a.groundingRatio);
  console.log(`\n✓ cross-review: ${results.length} reviewer(s) ran (ranked by file-grounded citations).\n`);
  for (const rev of results) {
    const g = rev.totalCitations
      ? `${rev.groundedCount}/${rev.totalCitations} citations resolve (ratio ${rev.groundingRatio.toFixed(2)})`
      : 'no path:line citations';
    console.log(`──── ${rev.name} — ${g}${rev.exit === 0 ? '' : ` [exit ${rev.exit}]`} ────`);
    console.log(rev.raw.trim() || '(no output)');
    console.log('');
  }
  console.log('Advisory only — this ran no tests and is not a gate. Weigh findings against the resolving citations.');
  return 0;
}

/** CLI entrypoint: `node review.mjs`. */
export function main() {
  const root = gitRoot();
  const cfg = loadConfig(root);
  return runReview(root, cfg);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}

/**
 * Deterministic seeded shuffle (H2-8, src: `harness2/core/selection.py::assign_ids` — candidate
 * IDs are canonical-sort + seeded-shuffle with `seed = sha1(task|k|mode)`). Pure: returns a NEW
 * array, never mutates the input, no I/O, no imports. APPEND-ONLY addition — defaultSpawn, the
 * review state machine, and CLI behavior are unchanged.
 *
 * Blind-selection use: strip authorship/provider labels from the candidates, canonical-sort them,
 * then `seededShuffle(sorted, seed)` so presentation order carries no authorship signal and the
 * outcome is reproducible from the seed. Non-answers are dropped by the caller with recorded
 * causes (see the orchestrator's blind-selection paragraph) — this helper only orders.
 *
 * Hash is cyrb53 (dependency-free string → 53-bit int) driving mulberry32 Fisher–Yates — chosen
 * over `node:crypto` so this block stays import-free and append-only.
 * @param {Array} arr candidates (already anonymized + canonical-sorted by the caller)
 * @param {string|number} seed e.g. `${task}|${k}|${mode}`
 * @returns {Array} new array in deterministic shuffled order
 */
export function seededShuffle(arr, seed) {
  const input = [...(arr || [])];
  // cyrb53 hash of the seed string.
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  const s = String(seed ?? '');
  for (let i = 0; i < s.length; i++) {
    const ch = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  let state = (h1 >>> 0) ^ (h2 >>> 0);
  // mulberry32 PRNG + Fisher–Yates.
  const rand = () => {
    state |= 0; state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = input.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [input[i], input[j]] = [input[j], input[i]];
  }
  return input;
}
