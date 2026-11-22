#!/usr/bin/env node
/**
 * @description Risk-based adversarial design-review validator (report-only first cut).
 * For plans declaring a high-risk trigger (T0/T1 impact, irreversible, dependency,
 * security/privacy, cross-tree), requires a `## Design Review Record` with a declared
 * risk trigger, at least three concrete concerns each carrying a response/evidence or
 * explicit uncertainty, and an approver decision. Low-risk and FAST PATH plans skip
 * unblocked; the existing recorded approval remains the only execution authority.
 *
 * Pure core (`checkDesignReview`) + a thin advisory CLI (`--file <plan.md>`).
 * Never wired into gates in this first cut.
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

export const RECORD_HEADING = '## Design Review Record';

/** High-risk trigger tokens (lowercased substring match against the declared trigger). */
export const HIGH_RISK_TRIGGERS = [
  't0',
  't1',
  'irreversible',
  'dependency',
  'dependencies',
  'security',
  'privacy',
  'cross-tree',
  'crosstree',
];

const FAST_PATH_RE = /FAST\s*PATH/i;
const TRIGGER_DECL_RE = /risk-?trigger\s*:\s*(.+)/i;
const DECISION_RE = /decision\s*:\s*(.+)/i;
const ITEM_RE = /^\s*(?:\d+[.)]|[-*])\s+(\S.*)$/;
const RESPONSE_RE = /(response|evidence)\s*:/i;
const UNCERTAINTY_RE = /uncertainty\s*:/i;

/** Extract the record section body (to the next same/higher heading), or null. */
export function extractRecordSection(content) {
  const lines = String(content || '').split('\n');
  const idx = lines.findIndex((l) => l.trim() === RECORD_HEADING);
  if (idx === -1) return null;
  const out = [];
  for (let i = idx + 1; i < lines.length; i++) {
    if (/^#{1,2}\s/.test(lines[i])) break;
    out.push(lines[i]);
  }
  return out.join('\n');
}

/**
 * Does this plan declare a high-risk trigger? FAST PATH with no trigger stays low-risk.
 * @returns {{highRisk:boolean, trigger:string|null, fastPath:boolean}}
 */
export function needsDesignReview(planContent) {
  const text = String(planContent || '');
  const fastPath = FAST_PATH_RE.test(text);
  const m = text.match(TRIGGER_DECL_RE);
  const trigger = m ? m[1].trim() : null;
  if (!trigger) return { highRisk: false, trigger: null, fastPath };
  const low = trigger.toLowerCase();
  const highRisk = HIGH_RISK_TRIGGERS.some((t) => low.includes(t));
  return { highRisk, trigger, fastPath };
}

/**
 * Pure check over already-loaded plan content.
 * @returns {{ok:boolean, skipped:boolean, errors:string[], warnings:string[]}}
 */
export function checkDesignReview(planContent, fileLabel = 'plan') {
  const errors = [];
  const warnings = [];
  const need = needsDesignReview(planContent);
  if (!need.highRisk) {
    return { ok: true, skipped: true, errors, warnings };
  }
  const section = extractRecordSection(planContent);
  if (section == null) {
    errors.push(`${fileLabel}: high-risk trigger "${need.trigger}" declares risk but has no "${RECORD_HEADING}" section`);
    return { ok: false, skipped: false, errors, warnings };
  }
  // Declared trigger inside the record must name a known high-risk token.
  const recTrigger = (section.match(TRIGGER_DECL_RE) || [])[1];
  if (!recTrigger || !recTrigger.trim()) {
    errors.push(`${fileLabel}: design review record is missing its declared risk trigger (Risk-Trigger: ...)`);
  } else if (!HIGH_RISK_TRIGGERS.some((t) => recTrigger.toLowerCase().includes(t))) {
    errors.push(`${fileLabel}: record risk trigger "${recTrigger.trim()}" names no known high-risk token — declare the risk or stop`);
  }
  // Concerns: ≥3 list items, each with a response/evidence or explicit uncertainty.
  const items = [];
  let current = null;
  for (const line of section.split('\n')) {
    const im = line.match(ITEM_RE);
    if (im && !/^(response|evidence|uncertainty|decision|risk-trigger)\s*:/i.test(im[1])) {
      if (current) items.push(current);
      current = line;
    } else if (current) {
      current += `\n${line}`;
    }
  }
  if (current) items.push(current);
  if (items.length < 3) {
    errors.push(`${fileLabel}: design review record lists ${items.length} concern(s) — at least 3 concrete concerns are required`);
  }
  items.forEach((item, i) => {
    if (!RESPONSE_RE.test(item) && !UNCERTAINTY_RE.test(item)) {
      errors.push(`${fileLabel}: concern ${i + 1} has neither a response/evidence nor an explicit uncertainty`);
    }
  });
  // Approver decision: non-empty Decision line.
  const decision = (section.match(DECISION_RE) || [])[1];
  if (!decision || !decision.trim()) {
    errors.push(`${fileLabel}: design review record is missing the approver decision (Decision: ...)`);
  }
  if (need.fastPath) {
    warnings.push(`${fileLabel}: FAST PATH plan declares high-risk trigger "${need.trigger}" — review still required`);
  }
  return { ok: errors.length === 0, skipped: false, errors, warnings };
}

/** CLI (advisory): exit 1 on a failing high-risk record, 0 when valid or skipped. */
export function main(argv) {
  const root = gitRoot();
  const i = argv.indexOf('--file');
  const file = i >= 0 ? argv[i + 1] : null;
  if (!file) {
    console.error('usage: verify-design-review.mjs --file <plan.md>');
    return 1;
  }
  const abs = path.isAbsolute(file) ? file : path.join(root, file);
  if (!existsSync(abs)) {
    console.error(`✗ design-review: file not found: ${file}`);
    return 1;
  }
  const res = checkDesignReview(readFileSync(abs, 'utf8'), file);
  for (const w of res.warnings) console.error(`! ${w}`);
  for (const e of res.errors) console.error(`✗ ${e}`);
  if (res.skipped) console.log(`✓ design-review: ${file} declares no high-risk trigger — no review required`);
  else if (res.ok) console.log(`✓ design-review: ${file} record complete`);
  return res.ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
