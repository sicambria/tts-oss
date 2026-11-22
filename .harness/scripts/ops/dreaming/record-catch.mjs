#!/usr/bin/env node
/**
 * @description `record-catch` CLI (wave3-A): append one real-usage gate firing
 * to the guardrail catch-ledger JSONL.
 *
 * Advisory-only BY CONSTRUCTION: this script only appends to a ledger file.
 * It is not wired into any gate chain, hook, or manifest, it never blocks a
 * commit, and it has no seed/backfill flag — provenance defaults to
 * `real-gate-failure` and anything else is rejected. Seeded or
 * incident-corpus-shaped input exits 1 with the rejection reason on stderr.
 *
 * Usage:
 *   node record-catch.mjs --gate <id> --stage <stage> [--defect <text>]
 *     [--ledger <path>] [--ts <iso>] [--json]
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../../lib/repo.mjs';
import { REAL_PROVENANCE } from './corpus.mjs';
import { HONESTY_HEADER, appendCatch } from './guardrail-ledger.mjs';

export const DEFAULT_LEDGER_REL = path.join('.harness', 'guardrail-catches.jsonl');

/** Absolute default ledger path for a repo root (committed JSONL). */
export function defaultLedgerPath(root) {
  return path.join(root, DEFAULT_LEDGER_REL);
}

/**
 * CLI entry. `opts.root` overrides repo-root detection (tests).
 * @param {string[]} argv argument list (without node/script)
 * @param {{ root?: string }} [opts]
 * @returns {number} exit code: 0 recorded-or-duplicate, 1 rejected, 2 usage
 */
export function main(argv, opts = {}) {
  const args = [...argv];
  if (args.includes('--help') || args.includes('-h')) {
    console.log(
      'record-catch --gate <id> --stage <stage> [--defect <text>] [--ledger <path>] [--ts <iso>] [--json]\n' +
        `Records one REAL gate firing. ${HONESTY_HEADER}.`,
    );
    return 0;
  }
  const get = (flag) => {
    const i = args.indexOf(flag);
    if (i === -1) return undefined;
    const val = args[i + 1];
    if (val === undefined || val.startsWith('--')) return undefined;
    return val;
  };
  const gate = get('--gate');
  const stage = get('--stage');
  const defect = get('--defect');
  const ts = get('--ts');
  const root = opts.root || gitRoot();
  const ledger = get('--ledger') || defaultLedgerPath(root);
  const asJson = args.includes('--json');

  if (!gate || !stage) {
    console.error('✗ record-catch: --gate <id> and --stage <stage> are required');
    return 2;
  }

  const entry = {
    gate,
    stage,
    ...(defect !== undefined ? { defect } : {}),
    ts: ts || new Date().toISOString(),
    provenance: REAL_PROVENANCE,
  };

  let result;
  try {
    result = appendCatch(path.resolve(ledger), entry);
  } catch (err) {
    console.error(`✗ record-catch: rejected — ${err instanceof Error ? err.message : String(err)}`);
    return 1;
  }

  if (asJson) {
    console.log(JSON.stringify({ ...result, honesty: HONESTY_HEADER }));
  } else if (result.recorded) {
    console.log(`✓ record-catch: recorded ${gate} @ ${stage} (advisory — ${HONESTY_HEADER})`);
  } else {
    console.log(`✓ record-catch: duplicate skipped for ${gate} @ ${stage} (advisory — not double-counted)`);
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
