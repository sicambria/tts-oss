#!/usr/bin/env node
/**
 * @description Anti-seeding guard for the guardrail catch-ledger (wave3-A).
 * The ledger records ONLY real gate failures in real use — never seeded,
 * synthetic, or incident-corpus-derived entries. Seeding would credit a guard
 * for the escape it encodes, manufacturing a firing history instead of
 * measuring one. This module is the single provenance authority: every other
 * dreaming module routes through `assertRealUsage` before recording.
 *
 * Pure core (no I/O, no CLI): `isSeededInput` / `assertRealUsage` /
 * `classifyProvenance` + `CatchValidationError`. Importable and unit-testable.
 */

/** The single accepted provenance: a gate that actually fired in real use. */
export const REAL_PROVENANCE = 'real-gate-failure';

/**
 * Provenance values that mark manufactured (non-real-usage) input. Any entry
 * carrying one is rejected — it describes a corpus escape, not a gate firing.
 */
export const SEEDED_PROVENANCES = new Set([
  'seeded',
  'incident-corpus',
  'synthetic',
  'imported-corpus',
  'benchmark-seeded',
]);

/**
 * Fields that link an entry back to the incident corpus (or any authored
 * fixture set) rather than to a live gate firing. Their presence marks the
 * entry as seeded no matter what `provenance` claims.
 */
const CORPUS_LINK_FIELDS = ['incidentId', 'corpusId', 'seedCorpus', 'fixtureId'];

/** Thrown when an entry is not admissible as a real-usage catch. */
export class CatchValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CatchValidationError';
  }
}

/**
 * Is this entry seeded (manufactured) rather than observed in real use?
 * @param {unknown} entry candidate catch record
 * @returns {{ seeded: boolean, reason: string|null }}
 */
export function isSeededInput(entry) {
  if (!entry || typeof entry !== 'object') {
    return { seeded: false, reason: null };
  }
  const e = /** @type {Record<string, unknown>} */ (entry);
  if (e.seeded === true) {
    return { seeded: true, reason: 'explicit seeded:true flag' };
  }
  if (typeof e.provenance === 'string' && SEEDED_PROVENANCES.has(e.provenance)) {
    return { seeded: true, reason: `seeded provenance ${JSON.stringify(e.provenance)}` };
  }
  for (const field of CORPUS_LINK_FIELDS) {
    if (e[field] !== undefined && e[field] !== null && e[field] !== '') {
      return { seeded: true, reason: `incident-corpus link field ${JSON.stringify(field)} is set` };
    }
  }
  return { seeded: false, reason: null };
}

/**
 * Classify an entry's provenance for reporting.
 * @param {unknown} entry
 * @returns {'real'|'seeded'|'unprovenanced'}
 */
export function classifyProvenance(entry) {
  if (!entry || typeof entry !== 'object') return 'unprovenanced';
  if (isSeededInput(entry).seeded) return 'seeded';
  const p = /** @type {Record<string, unknown>} */ (entry).provenance;
  if (p === REAL_PROVENANCE) return 'real';
  return 'unprovenanced';
}

/**
 * Assert an entry is admissible: not seeded AND explicitly real-usage.
 * Anything else — seeded, synthetic, incident-linked, missing, or merely
 * unprovenanced — is rejected. There is no waiver: the ledger has no
 * backfill path by design.
 * @param {unknown} entry candidate catch record
 * @throws {CatchValidationError} on any non-real-usage input
 */
export function assertRealUsage(entry) {
  const { seeded, reason } = isSeededInput(entry);
  if (seeded) {
    throw new CatchValidationError(
      `catch-ledger: seeded/incident-corpus input rejected (${reason}) — ` +
        'the ledger records only real gate failures',
    );
  }
  const provenance =
    entry && typeof entry === 'object'
      ? /** @type {Record<string, unknown>} */ (entry).provenance
      : undefined;
  if (provenance !== REAL_PROVENANCE) {
    throw new CatchValidationError(
      `catch-ledger: provenance must be ${JSON.stringify(REAL_PROVENANCE)}, ` +
        `got ${JSON.stringify(provenance)} — only real gate failures are recorded`,
    );
  }
}
