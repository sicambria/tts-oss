#!/usr/bin/env node
/**
 * @description Guardrail catch-ledger pure core (wave3-A, port of changemappers
 * `scripts/ops/dreaming/guardrail-ledger.mjs`).
 *
 * Records which gate caught which defect at which stage into an append-only
 * JSONL, driven ONLY by real gate failures (provenance is enforced through
 * `corpus.mjs` — seeded/incident-corpus input is rejected, never stored).
 *
 * HONESTY CONTRACT (load-bearing, same discipline as the SOTA scorecard's
 * `[P]`/`[H]` presence-vs-health legend): this ledger counts which gates FIRE
 * in real use — "which gates earn their keep." It does NOT measure
 * false-block rates, miss rates, or gate efficacy. Every summary carries that
 * caveat in-band (`HONESTY_HEADER`); presenting firing counts as efficacy is
 * the exact overclaim the ledger exists to avoid.
 *
 * Pure core + file helpers (`appendCatch`/`readCatches`); no CLI here (see
 * `record-catch.mjs`), no gate wiring, no manifest — advisory-only by
 * construction. Reading never throws (mirrors `ops/events.mjs`): a missing
 * file yields `[]`, malformed lines are skipped.
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import {
  CatchValidationError,
  REAL_PROVENANCE,
  assertRealUsage,
  isSeededInput,
} from './corpus.mjs';

export { CatchValidationError, REAL_PROVENANCE };

/** In-band honesty caveat attached to every summary and rendering. */
export const HONESTY_HEADER = 'Catch-ledger: FIRINGS, NOT EFFICACY';
export const HONESTY_LABEL =
  'which gates earn their keep — counts of real gate firings per gate. ' +
  'NOT false-block rates, NOT miss rates, NOT gate efficacy.';

/**
 * Validate a catch entry without writing anything.
 * @param {unknown} entry candidate catch record
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateCatch(entry) {
  const errors = [];
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    return { ok: false, errors: ['catch must be an object'] };
  }
  const e = /** @type {Record<string, unknown>} */ (entry);
  if (typeof e.gate !== 'string' || !e.gate.trim()) {
    errors.push('gate is required (non-empty string: the firing gate id)');
  }
  if (typeof e.stage !== 'string' || !e.stage.trim()) {
    errors.push('stage is required (non-empty string: where the gate fired)');
  }
  if (typeof e.ts !== 'string' || Number.isNaN(Date.parse(e.ts))) {
    errors.push('ts is required (ISO timestamp of the real firing)');
  }
  if (e.defect !== undefined && typeof e.defect !== 'string') {
    errors.push('defect, when present, must be a string');
  }
  try {
    assertRealUsage(entry);
  } catch (err) {
    errors.push(err instanceof Error ? err.message : String(err));
  }
  return { ok: errors.length === 0, errors };
}

/**
 * Canonical dedupe key: same gate + stage + defect + timestamp is the same
 * observed firing. Re-recording it must not double-count the gate.
 * @param {Record<string, unknown>} entry validated catch record
 */
export function catchKey(entry) {
  return [entry.gate, entry.stage, entry.defect || '', entry.ts].join('|');
}

/**
 * Read every catch from a JSONL ledger. Returns `[]` when the file does not
 * exist; skips malformed lines. Never throws.
 * @param {string} ledgerPath absolute path to the JSONL ledger
 * @returns {Array<Record<string, unknown>>}
 */
export function readCatches(ledgerPath) {
  if (!existsSync(ledgerPath)) return [];
  let raw;
  try {
    raw = readFileSync(ledgerPath, 'utf8');
  } catch {
    return [];
  }
  const out = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === 'object') out.push(parsed);
    } catch {
      /* skip bad line — observability never blocks */
    }
  }
  return out;
}

/**
 * Validate + append one real-usage catch. Seeded/incident-corpus input throws
 * (it is rejected, never stored). Exact duplicates are skipped idempotently.
 * @param {string} ledgerPath absolute path to the JSONL ledger
 * @param {Record<string, unknown>} entry candidate catch record
 * @returns {{ recorded: boolean, reason: string, record: Record<string, unknown> }}
 * @throws {CatchValidationError} on invalid or non-real-usage input
 */
export function appendCatch(ledgerPath, entry) {
  const { ok, errors } = validateCatch(entry);
  if (!ok) {
    throw new CatchValidationError(`catch-ledger: invalid catch — ${errors.join('; ')}`);
  }
  const record = { ...entry };
  const key = catchKey(record);
  const existing = readCatches(ledgerPath);
  if (existing.some((c) => catchKey(c) === key)) {
    return { recorded: false, reason: 'duplicate', record };
  }
  mkdirSync(path.dirname(ledgerPath), { recursive: true });
  appendFileSync(ledgerPath, JSON.stringify(record) + '\n');
  return { recorded: true, reason: 'recorded', record };
}

/**
 * Summarize firing counts per gate. Counts are firings in real use — the
 * returned object always carries the honesty caveat in-band.
 * @param {Array<Record<string, unknown>>} entries
 */
export function summarizeCatches(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const byGate = {};
  for (const e of list) {
    const gate = (e && typeof e.gate === 'string' && e.gate) || 'unknown';
    byGate[gate] = (byGate[gate] || 0) + 1;
  }
  return {
    total: list.length,
    byGate,
    honestyHeader: HONESTY_HEADER,
    honesty: HONESTY_LABEL,
    seededAdmitted: list.filter((e) => isSeededInput(e).seeded).length,
  };
}

/**
 * Render a summary as human-readable text. The honesty header is always the
 * first line so firing counts can never be quoted without the caveat.
 * @param {ReturnType<typeof summarizeCatches>} summary
 */
export function renderSummary(summary) {
  const lines = [
    HONESTY_HEADER,
    HONESTY_LABEL,
    `total firings: ${summary.total}`,
  ];
  for (const [gate, count] of Object.entries(summary.byGate).sort()) {
    lines.push(`  ${gate}: ${count}`);
  }
  return lines.join('\n') + '\n';
}
