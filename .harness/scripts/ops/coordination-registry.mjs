#!/usr/bin/env node
/**
 * @description Two-layer work-claim registry, agent-side half (wave4-C, port of changemappers
 * `scripts/ops/coordination-registry.mjs` per research/imports/2026-07-11-changemappers-gate-integrity.md).
 *
 * RE-SCOPED (advisor blocking fix): this registry lives in a SEPARATE file — the gitignored
 * live fragment `.harness/state/work-claims.jsonl` and/or any NEW tracked file the caller names.
 * It reads the orchestrator claims ledger (`plan.claimsFile`,
 * `docs/plans/worktree-current-state.md`) READ-ONLY for display (`readLedgerClaims`) and NEVER
 * appends to it — the orchestrator owns that file, and concurrent agent appends race at merge.
 * Every writer in this module refuses the ledger path (`assertNotLedgerPath`); any prompt or
 * plan text telling an agent to append to the claims ledger is overridden by that refusal.
 *
 * SCOPE CONTRACT (same honesty discipline as the catch-ledger's FIRINGS-NOT-EFFICACY header):
 * this registry tracks liveness signals to avoid double-implementation across a fleet. It does
 * NOT authenticate agents, does NOT guarantee exclusivity, and a live claim is a signal, not a
 * lock — the single serial merge point remains the correctness backstop.
 *
 * Event-fold design (CALM-monotonic, no shared-file conflict): writers only APPEND small JSONL
 * events (`register`/`heartbeat`/`release`); readers fold to latest-per-branch and filter by
 * liveness (`process.kill(pid,0)` reaps crashed claims). Append-only means concurrent agents
 * never read-modify-write the same bytes. `reapStale` compaction is orchestrator-serial and
 * commits atomically (tmp-file + rename).
 *
 * Pure core + file helpers; no CLI here, no gate wiring, no manifest. Reading never throws
 * (mirrors `ops/events.mjs` and `dreaming/guardrail-ledger.mjs`): a missing file yields `[]`,
 * malformed lines are skipped.
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** Default orchestrator-owned ledger path (relative to repo root). Writers refuse it. */
export const DEFAULT_CLAIMS_FILE = 'docs/plans/worktree-current-state.md';

/** Default live-fragment path (gitignored runtime state, not a tracked claim). */
export const DEFAULT_REGISTRY_FILE = '.harness/state/work-claims.jsonl';

export const EVENT_TYPES = ['register', 'heartbeat', 'release'];

export class ClaimValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ClaimValidationError';
  }
}

/** Thrown when a writer is pointed at the orchestrator-owned claims ledger. */
export class LedgerWriteError extends Error {
  constructor(message) {
    super(message);
    this.name = 'LedgerWriteError';
  }
}

/**
 * True iff `target` resolves to the orchestrator-owned claims ledger. Pure (no I/O):
 * compares normalized absolute paths so `./docs/...`, `docs/...`, and absolute forms match.
 * @param {string} target candidate write target
 * @param {{ claimsFile?: string, repoRoot?: string }} [opts]
 */
export function isLedgerPath(target, opts = {}) {
  const claimsFile = opts.claimsFile || DEFAULT_CLAIMS_FILE;
  const root = opts.repoRoot || process.cwd();
  return path.resolve(root, target) === path.resolve(root, claimsFile);
}

/**
 * Fail-closed refusal: writers call this first. Any instruction to append agent claims to
 * the orchestrator ledger — however phrased, wherever sourced — dies here, never at merge.
 * @param {string} target candidate write target
 * @param {{ claimsFile?: string, repoRoot?: string }} [opts]
 */
export function assertNotLedgerPath(target, opts = {}) {
  if (isLedgerPath(target, opts)) {
    throw new LedgerWriteError(
      `refusing to write agent work-claim to the orchestrator-owned ledger "${opts.claimsFile || DEFAULT_CLAIMS_FILE}": ` +
        'the registry lives in a separate file; the ledger is read-only for agents',
    );
  }
}

/**
 * Default liveness probe: `process.kill(pid, 0)` reaps crashed claims without signalling.
 * ESRCH (no such process) means dead; EPERM (no permission) means alive — the process
 * exists, we just cannot signal it. Anything else fails closed to dead.
 * @param {number} pid
 */
export function defaultIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    if (err && typeof err === 'object' && 'code' in err && err.code === 'EPERM') return true;
    return false;
  }
}

/**
 * Validate a claim without writing anything.
 * @param {unknown} claim candidate claim record
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateClaim(claim) {
  const errors = [];
  if (!claim || typeof claim !== 'object' || Array.isArray(claim)) {
    return { ok: false, errors: ['claim must be an object'] };
  }
  const c = /** @type {Record<string, unknown>} */ (claim);
  if (typeof c.branch !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(c.branch)) {
    errors.push('branch is required (non-empty: letters/digits plus . _ / -)');
  }
  if (typeof c.pid !== 'number' || !Number.isInteger(c.pid) || c.pid <= 0) {
    errors.push('pid is required (positive integer: the claiming process)');
  }
  if (c.ts !== undefined && (typeof c.ts !== 'string' || Number.isNaN(Date.parse(c.ts)))) {
    errors.push('ts, when present, must be an ISO timestamp');
  }
  if (c.agent !== undefined && (typeof c.agent !== 'string' || !c.agent.trim())) {
    errors.push('agent, when present, must be a non-empty string');
  }
  return { ok: errors.length === 0, errors };
}

/**
 * Read every claim event from a JSONL registry fragment. Never throws: a missing file
 * yields `[]`, malformed lines are skipped.
 * @param {string} file registry fragment path
 * @returns {Array<Record<string, unknown>>}
 */
export function readEvents(file) {
  if (!existsSync(file)) return [];
  const out = [];
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try {
      const e = JSON.parse(t);
      if (e && typeof e === 'object' && EVENT_TYPES.includes(e.type)) out.push(e);
    } catch { /* malformed line — skip */ }
  }
  return out;
}

function ensureParent(file) {
  mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
}

/**
 * Append one event to the registry fragment. O_APPEND single-write: concurrent agents
 * appending small lines never interleave mid-line and never read-modify-write.
 */
function appendEvent(file, event, opts = {}) {
  assertNotLedgerPath(file, opts);
  ensureParent(file);
  appendFileSync(file, JSON.stringify(event) + '\n', { encoding: 'utf8' });
}

/**
 * Register a live work-claim for `branch` from `pid`. Refuses the ledger path.
 * @param {string} file registry fragment path (NOT the orchestrator ledger)
 * @param {{ branch: string, pid: number, agent?: string, ts?: string }} claim
 * @param {{ claimsFile?: string, repoRoot?: string, now?: () => string }} [opts]
 */
export function registerClaim(file, claim, opts = {}) {
  const { ok, errors } = validateClaim({ ...claim, ts: claim.ts ?? new Date().toISOString() });
  if (!ok) throw new ClaimValidationError(`invalid work-claim rejected: ${errors.join('; ')}`);
  const event = {
    v: 1,
    type: 'register',
    branch: claim.branch,
    pid: claim.pid,
    ts: claim.ts ?? (opts.now ? opts.now() : new Date().toISOString()),
    ...(claim.agent !== undefined ? { agent: claim.agent } : {}),
  };
  appendEvent(file, event, opts);
  return { recorded: true, event };
}

/**
 * Heartbeat a prior registration (keeps a long-lived claim fresh). Throws — and stores
 * nothing — when no non-released `register` exists for this (branch, pid).
 */
export function heartbeatClaim(file, { branch, pid }, opts = {}) {
  const { ok, errors } = validateClaim({ branch, pid });
  if (!ok) throw new ClaimValidationError(`invalid heartbeat rejected: ${errors.join('; ')}`);
  const prior = readEvents(file).some(
    (e) => e.branch === branch && e.pid === pid && (e.type === 'register' || e.type === 'heartbeat'),
  );
  if (!prior) {
    throw new ClaimValidationError(
      `heartbeat rejected: no live registration for branch "${branch}" pid ${pid} — register first`,
    );
  }
  const event = {
    v: 1,
    type: 'heartbeat',
    branch,
    pid,
    ts: opts.now ? opts.now() : new Date().toISOString(),
  };
  appendEvent(file, event, opts);
  return { recorded: true, event };
}

/**
 * Release a claim (branch integrated or abandoned). Always recorded, even for unknown
 * claims — release is idempotent by construction.
 */
export function releaseClaim(file, { branch, pid }, opts = {}) {
  const { ok, errors } = validateClaim({ branch, pid });
  if (!ok) throw new ClaimValidationError(`invalid release rejected: ${errors.join('; ')}`);
  const event = {
    v: 1,
    type: 'release',
    branch,
    pid,
    ts: opts.now ? opts.now() : new Date().toISOString(),
  };
  appendEvent(file, event, opts);
  return { recorded: true, event };
}

/**
 * Fold events to the live set: latest event per branch wins; a branch is live iff its
 * latest event is not a `release` AND its pid still answers `process.kill(pid, 0)`.
 * Pure (takes events, no I/O) so it is unit-testable with a fake probe.
 * @param {Array<Record<string, unknown>>} events
 * @param {{ isAlive?: (pid: number) => boolean }} [opts]
 */
export function foldLive(events, opts = {}) {
  const isAlive = opts.isAlive || defaultIsAlive;
  const latest = new Map();
  for (const e of events) {
    if (!e || typeof e.branch !== 'string') continue;
    latest.set(e.branch, e);
  }
  const live = [];
  for (const [branch, e] of latest) {
    if (e.type === 'release') continue;
    if (typeof e.pid !== 'number' || !isAlive(e.pid)) continue;
    live.push({ branch, pid: e.pid, ts: e.ts, ...(e.agent !== undefined ? { agent: e.agent } : {}) });
  }
  live.sort((a, b) => (a.branch < b.branch ? -1 : a.branch > b.branch ? 1 : 0));
  return live;
}

/**
 * Live claims in a registry fragment. Never throws on missing/malformed input.
 * @param {string} file registry fragment path
 * @param {{ isAlive?: (pid: number) => boolean }} [opts]
 */
export function liveClaims(file, opts = {}) {
  return foldLive(readEvents(file), opts);
}

/**
 * Compact the fragment to one `register` event per live claim, dropping dead-pid and
 * released branches. Orchestrator-serial; commits atomically via tmp-file + rename.
 * Refuses the ledger path. Returns `{ kept, reaped }`.
 */
export function reapStale(file, opts = {}) {
  assertNotLedgerPath(file, opts);
  const live = liveClaims(file, opts);
  const before = readEvents(file).length;
  const body = live
    .map((c) => JSON.stringify({ v: 1, type: 'register', branch: c.branch, pid: c.pid, ts: c.ts, ...(c.agent !== undefined ? { agent: c.agent } : {}) }))
    .join('\n');
  ensureParent(file);
  const tmp = `${file}.reap-${process.pid}.tmp`;
  writeFileSync(tmp, body ? body + '\n' : '', { encoding: 'utf8' });
  renameSync(tmp, file);
  return { kept: live.length, reaped: before - live.length };
}

/**
 * READ-ONLY display view over the orchestrator-owned claims ledger (`plan.claimsFile`).
 * Extracts `(branch \`name\`)` markers as `{ branch }` rows for fleet visibility. Never
 * throws (missing file yields `[]`) and — by construction, taking no write target —
 * cannot append to the ledger.
 * @param {string} [claimsFile] ledger path; defaults to `docs/plans/worktree-current-state.md`
 * @param {{ repoRoot?: string }} [opts]
 */
export function readLedgerClaims(claimsFile = DEFAULT_CLAIMS_FILE, opts = {}) {
  const abs = path.resolve(opts.repoRoot || process.cwd(), claimsFile);
  if (!existsSync(abs)) return [];
  const text = readFileSync(abs, 'utf8');
  const out = [];
  const seen = new Set();
  const re = /\(branch `([^`]+)`\)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (!seen.has(m[1])) {
      seen.add(m[1]);
      out.push({ branch: m[1] });
    }
  }
  return out;
}
