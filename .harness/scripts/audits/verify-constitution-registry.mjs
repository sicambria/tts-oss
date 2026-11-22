#!/usr/bin/env node
/**
 * @description Constitution registry static audit (report-only first cut).
 * `.harness/constitution.md` stays the sole authority. This audit only checks OPTIONAL
 * registry rows — markdown table rows of the form
 * `| <ID> | <principle> | <control> | <decision> |` — for three defects: duplicate
 * IDs, missing decision links, and control identifiers outside the static allowlist
 * of real gate/test paths. It reads files and manifest IDs only and NEVER executes
 * Markdown (no eval, no shell, no dynamic import of documentation values).
 *
 * Pure core (`parseRegistryRows` / `auditRegistry`) + a thin advisory CLI.
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

/** Registry-row ID shape: `C.1`, `T0.4`, `REG-<slug>` … */
export const REGISTRY_ID_RE = /^[A-Za-z]+\.?\d[\w.-]*$|^REG-[\w-]+$/;

/** Static allowlist of real control identifiers (gate/test paths that exist). */
export const DEFAULT_KNOWN_CONTROLS = [
  '.harness/scripts/verify.mjs',
  '.harness/scripts/audits/verify-plan-evidence.mjs',
  '.harness/scripts/audits/verify-test-gaming.mjs',
  '.harness/scripts/audits/verify-decision-log.mjs',
  '.harness/scripts/audits/verify-secrets.mjs',
  '.harness/scripts/audits/verify-canary.mjs',
  '.harness/INVARIANTS.md',
  '.harness/constitution.md',
];

/**
 * Parse optional registry rows from markdown. Only table rows whose first cell
 * matches REGISTRY_ID_RE count; every other line/table is ignored (rows are optional).
 * @returns {Array<{id:string, principle:string, control:string, decision:string, line:number}>}
 */
export function parseRegistryRows(markdown) {
  const rows = [];
  String(markdown || '').split('\n').forEach((line, i) => {
    const cells = line.split('|').map((c) => c.trim());
    // `| a | b | c | d |` splits into ['', a, b, c, d, ''].
    if (cells.length < 6 || cells[0] !== '' || cells[cells.length - 1] !== '') return;
    const [, id, principle, control, decision] = cells;
    if (!REGISTRY_ID_RE.test(id)) return;
    if (/^-+$/.test(principle) || /^-+$/.test(control)) return; // separator row
    rows.push({ id, principle, control, decision, line: i + 1 });
  });
  return rows;
}

/**
 * Pure static audit. `knownControls` is an explicit allowlist of gate/test identifiers.
 * @returns {{ok:boolean, rows:number, errors:string[], warnings:string[]}}
 */
export function auditRegistry({ markdown = '', knownControls = DEFAULT_KNOWN_CONTROLS, fileLabel = 'registry' } = {}) {
  const errors = [];
  const warnings = [];
  const rows = parseRegistryRows(markdown);
  if (rows.length === 0) {
    warnings.push(`${fileLabel}: no registry rows found — registry is optional; constitution remains the sole authority`);
    return { ok: true, rows: 0, errors, warnings };
  }
  const seen = new Map();
  for (const r of rows) {
    if (seen.has(r.id)) {
      errors.push(`${fileLabel}:${r.line}: duplicate registry ID "${r.id}" (first at line ${seen.get(r.id)})`);
    } else {
      seen.set(r.id, r.line);
    }
    if (!r.decision || !/[/.]/.test(r.decision)) {
      errors.push(`${fileLabel}:${r.line}: registry row "${r.id}" has no logged-decision link (decision record path required)`);
    }
    if (!knownControls.includes(r.control)) {
      errors.push(`${fileLabel}:${r.line}: registry row "${r.id}" references unknown control "${r.control}" (not in the static allowlist)`);
    }
  }
  return { ok: errors.length === 0, rows: rows.length, errors, warnings };
}

/** CLI (advisory): reads files only; exit 1 on audit defects, 0 otherwise. */
export function main(argv) {
  const root = gitRoot();
  const fi = argv.indexOf('--file');
  const file = fi >= 0 ? argv[fi + 1] : null;
  if (!file) {
    console.error('usage: verify-constitution-registry.mjs --file <registry.md> [--controls a,b,c]');
    return 1;
  }
  const ci = argv.indexOf('--controls');
  const knownControls = ci >= 0 && argv[ci + 1] ? argv[ci + 1].split(',') : DEFAULT_KNOWN_CONTROLS;
  const abs = path.isAbsolute(file) ? file : path.join(root, file);
  if (!existsSync(abs)) {
    console.error(`✗ constitution-registry: file not found: ${file}`);
    return 1;
  }
  // Static read only — documentation values are data, never code.
  const res = auditRegistry({ markdown: readFileSync(abs, 'utf8'), knownControls, fileLabel: file });
  for (const w of res.warnings) console.error(`! ${w}`);
  for (const e of res.errors) console.error(`✗ ${e}`);
  if (res.ok) console.log(`✓ constitution-registry: ${res.rows} row(s) grounded`);
  return res.ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
