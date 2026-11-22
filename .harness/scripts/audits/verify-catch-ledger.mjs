#!/usr/bin/env node
/**
 * @description Catch-ledger advisory gate (ratchet2, wave5-R). Reads the real-usage guardrail
 * firing ledger (`.harness/guardrail-catches.jsonl`, written ONLY by `record-catch.mjs` for
 * real gate failures — seeded/incident-corpus input is rejected, never stored) and reports
 * which gates earn their keep.
 *
 * ADVISORY-ONLY first cut: this gate WARNS (exit 0) and never fails closed — promotion to
 * fail-closed is a later wave after one dogfood cycle. `main()` returns 0 unconditionally;
 * findings are `{rule, message}` warnings. Follows the harness-surface advisory pattern
 * (ratchet1): record-only, never blocks.
 *
 * HONESTY CONTRACT (same discipline as the ledger core): counts are FIRINGS, never efficacy —
 * every rendering carries `HONESTY_HEADER` in-band so firing counts can never be quoted as
 * efficacy, false-block, or miss rates.
 *
 * Pure core (`checkCatchLedgerAt` over a repo root) + a thin CLI. Zero model cost.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { DEFAULT_LEDGER_REL } from '../ops/dreaming/record-catch.mjs';
import {
  HONESTY_HEADER,
  readCatches,
  renderSummary,
  summarizeCatches,
} from '../ops/dreaming/guardrail-ledger.mjs';

/**
 * Advisory check of the catch ledger under a repo root. Never throws on a missing ledger
 * (absent file yields zero firings, not an error) and never fails — findings are warnings.
 * @param {string} root repo root
 * @returns {{warnings:{rule:string, message:string}[], total:number, summary:string}}
 */
export function checkCatchLedgerAt(root) {
  const entries = readCatches(path.join(root, DEFAULT_LEDGER_REL));
  const summary = summarizeCatches(entries);
  const text = renderSummary(summary);
  const warnings =
    summary.total === 0
      ? [{ rule: 'ledger-empty', message: 'catch-ledger is empty — no real gate firings recorded yet' }]
      : Object.entries(summary.byGate)
          .sort(([a], [b]) => (a < b ? -1 : 1))
          .map(([gate, count]) => ({
            rule: 'gate-firing',
            message: `gate "${gate}" fired ${count} time(s) in real use — ${HONESTY_HEADER}`,
          }));
  return { warnings, total: summary.total, summary: text };
}

/** CLI: print the ledger summary, ALWAYS exit 0 (advisory-only first cut — never fail-closed). */
export function main(argv = []) {
  void argv;
  const root = gitRoot();
  const { warnings, summary } = checkCatchLedgerAt(root);
  for (const w of warnings) console.error(`! catch-ledger [${w.rule}]: ${w.message}`);
  console.error(summary.trimEnd());
  console.error(
    `~ catch-ledger: ${warnings.length} advisory note(s) — non-blocking (promotion to fail-closed is a later wave)`,
  );
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
