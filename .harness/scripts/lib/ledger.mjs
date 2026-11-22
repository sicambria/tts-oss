#!/usr/bin/env node
/**
 * @description Budget ledger (H2-7, src: `harness2/core/ledger.py`). Tracks multi-candidate spend
 * for parallel waves (agent-protocol), planmax k>1 iterations, and benchmark sweeps: every rollout
 * and every improvement stage is recorded with its USD cost, and `assert_identity()` fails the run
 * unless the counts match the recursion budget **R = 4k rollouts, P = 3k stages** with **no
 * duplicate label**.
 *
 * Duplicate labels are checked FIRST, because a duplicate can satisfy the counts: a repeated label
 * means a run-id collision silently overwrote (or double-counted) a candidate, so a count-only
 * check would pass a corrupted ledger. Mirrors `Ledger.assert_identity()` / `BudgetError`.
 *
 * Stable-order-after-concurrency: concurrent phases must record their stage entries AFTER the pool
 * drains, in canonical (sorted-label) order, via `recordSessionsStable()` — so a concurrent run
 * records the same label sequence as a serial one (mirrors `_record_sessions` running after
 * `_roll_many` drains in `harness2/core/recursion.py`).
 *
 * Pure core (`Ledger`, `expectedRollouts`, `expectedStages`, `BudgetError`) + no CLI: consumers
 * construct a ledger, record, and assert. Never throws except `BudgetError`.
 */

export const ROLLOUTS_PER_K = 4;
export const STAGES_PER_K = 3;

/** Raised by `assert_identity()` (and the constructor) on any budget-identity violation. */
export class BudgetError extends Error {
  constructor(message) {
    super(message);
    this.name = 'BudgetError';
  }
}

/**
 * Expected rollout count for recursion budget k: R = 4k.
 * @param {number} k positive integer recursion budget
 */
export function expectedRollouts(k) {
  return ROLLOUTS_PER_K * k;
}

/**
 * Expected improvement-stage count for recursion budget k: P = 3k.
 * @param {number} k positive integer recursion budget
 */
export function expectedStages(k) {
  return STAGES_PER_K * k;
}

function checkK(k) {
  if (!Number.isInteger(k) || k < 1) {
    throw new BudgetError(`ledger: k must be a positive integer, got ${JSON.stringify(k)}`);
  }
}

/**
 * Find labels occurring more than once across the given label lists.
 * @param {...string[]} lists
 * @returns {string[]} sorted duplicate labels
 */
export function findDuplicateLabels(...lists) {
  const seen = new Set();
  const dupes = new Set();
  for (const list of lists) {
    for (const label of list) {
      if (seen.has(label)) dupes.add(label);
      else seen.add(label);
    }
  }
  return [...dupes].sort();
}

export class Ledger {
  /**
   * @param {{k: number, mode?: string, seed?: string|null}} opts
   */
  constructor({ k, mode = 'parallel', seed = null } = {}) {
    checkK(k);
    this.k = k;
    this.mode = mode;
    this.seed = seed;
    this.rollouts = []; // [{ label, usd }]
    this.sessions = []; // [{ label, usd }] — improvement stages, P = 3k
  }

  /**
   * Record one rollout (candidate execution) with its USD cost.
   * @param {string} label unique run label, e.g. `<task>|inv|0`
   * @param {{usd?: number}} [opts]
   */
  recordRollout(label, { usd = 0 } = {}) {
    this.rollouts.push({ label: String(label), usd: Number(usd) || 0 });
  }

  /**
   * Record one improvement stage with its USD cost. For concurrent phases, prefer
   * `recordSessionsStable()` after the pool drains so the label sequence is stable.
   * @param {string} label unique stage label, e.g. `<task>|stage|0`
   * @param {{usd?: number}} [opts]
   */
  recordSession(label, { usd = 0 } = {}) {
    this.sessions.push({ label: String(label), usd: Number(usd) || 0 });
  }

  /**
   * Record stage entries produced concurrently, in canonical sorted-label order, AFTER the pool
   * drains. Concurrent completion order must never leak into the ledger: the same entry set
   * recorded via this method always yields the same label sequence as a serial run.
   * @param {Array<{label: string, usd?: number}>} entries
   */
  recordSessionsStable(entries) {
    const sorted = [...(entries || [])].sort((a, b) =>
      String(a.label) < String(b.label) ? -1 : String(a.label) > String(b.label) ? 1 : 0,
    );
    for (const e of sorted) this.recordSession(e.label, { usd: e.usd });
  }

  /** Recorded rollout labels in record order. */
  rolloutLabels() {
    return this.rollouts.map((r) => r.label);
  }

  /** Recorded stage labels in record order. */
  sessionLabels() {
    return this.sessions.map((s) => s.label);
  }

  /** Accumulated USD across all rollouts and stages. */
  totalUSD() {
    return [...this.rollouts, ...this.sessions].reduce((sum, e) => sum + e.usd, 0);
  }

  /**
   * Assert the budget identity: no duplicate label (checked FIRST — a duplicate can satisfy the
   * counts and signals a run-id collision), then R = 4k rollouts and P = 3k stages exactly.
   * @throws {BudgetError} on any violation
   * @returns {{k: number, mode: string, R: number, P: number, usd: number}} identity summary
   */
  assert_identity() {
    const dupes = findDuplicateLabels(this.rolloutLabels(), this.sessionLabels());
    if (dupes.length > 0) {
      throw new BudgetError(
        `ledger: duplicate label(s) ${JSON.stringify(dupes)} — a repeated label means a run-id ` +
          `collision silently overwrote or double-counted a candidate (counts checked only after this)`,
      );
    }
    const wantR = expectedRollouts(this.k);
    const wantP = expectedStages(this.k);
    if (this.rollouts.length !== wantR || this.sessions.length !== wantP) {
      throw new BudgetError(
        `ledger: budget identity violated for k=${this.k} (${this.mode}): ` +
          `R=${this.rollouts.length} (want ${wantR}), P=${this.sessions.length} (want ${wantP})`,
      );
    }
    return { k: this.k, mode: this.mode, R: this.rollouts.length, P: this.sessions.length, usd: this.totalUSD() };
  }
}
