#!/usr/bin/env node
/**
 * @description THE CROWN JEWEL (genericized). Script-verified plan-evidence grounding:
 * a plan's "## Standards & Guardrails Evidence" section must cite `path:line` references that
 * RESOLVE against the working tree — a hallucinated/nonexistent path HARD-FAILS the commit —
 * and must check off every configured evidence dimension (with a resolving citation or an explicit
 * `N/A — reason`). "Citation resolution attacks wrong-facts; the dimension checklist attacks
 * didn't-consider."
 *
 * Two modes (config.plan.evidenceMode):
 *   - 'grounding'  (default): full citation resolution + dimensions.
 *   - 'structural' (M1 de-risk fallback): heading + dimensions present, no path resolution.
 *
 * Pure core (`checkPlanEvidence`) + a CLI that checks staged plan files (or --file <path>).
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot, stagedPaths, readRepoFile } from '../lib/repo.mjs';

const CITATION = /([A-Za-z0-9_./-]+\.[A-Za-z0-9]+):(\d+)/g;
const PLACEHOLDER = /\b(TBD|FIXME|XXX|<stub>)\b/;
const NA = /\bN\/A\b\s*[—-]/i; // "N/A — reason"

/** Strip inline code spans so `Promise<void>` / `foo.ts` in backticks aren't scanned. */
function stripInlineCode(s) {
  return s.replace(/`[^`]*`/g, '');
}

/** Extract the evidence section body (from the heading to the next same/higher heading). */
function evidenceSection(content, heading) {
  const lines = content.split('\n');
  const idx = lines.findIndex((l) => l.trim() === heading.trim());
  if (idx === -1) return null;
  const level = (heading.match(/^#+/) || ['##'])[0].length;
  const out = [];
  for (let i = idx + 1; i < lines.length; i++) {
    const m = lines[i].match(/^(#+)\s/);
    if (m && m[1].length <= level) break;
    out.push(lines[i]);
  }
  return out.join('\n');
}

/**
 * Core check over already-loaded content.
 * @param {string} content plan file content
 * @param {{repoRoot:string, config:object, fileLabel?:string}} ctx
 * @returns {{ok:boolean, errors:string[], warnings:string[]}}
 */
export function checkPlanEvidence(content, ctx) {
  const { config } = ctx;
  const heading = config.plan?.evidenceHeading || '## Standards & Guardrails Evidence';
  const mode = config.plan?.evidenceMode || 'grounding';
  const dims = (config.plan?.dimensions || []).map((d) => d.key);
  const errors = [];
  const warnings = [];
  const label = ctx.fileLabel || 'plan';

  const section = evidenceSection(content, heading);
  if (section == null) {
    errors.push(`${label}: missing required section "${heading}"`);
    return { ok: false, errors, warnings };
  }

  const scanned = stripInlineCode(section);

  // Placeholder scan (both modes).
  if (PLACEHOLDER.test(scanned)) {
    errors.push(`${label}: evidence section contains a placeholder (TBD/FIXME/XXX/<stub>) — ground it or mark N/A`);
  }

  // Dimension checklist (both modes): each configured dimension must appear as a checked bullet.
  for (const dim of dims) {
    const re = new RegExp(`-\\s*\\[x\\]\\s*.*${dim.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'i');
    const line = section.split('\n').find((l) => re.test(l));
    if (!line) {
      errors.push(`${label}: evidence dimension not checked off: "${dim}" (use "- [x] ${dim}: <path:line>" or "N/A — reason")`);
      continue;
    }
    if (mode === 'grounding') {
      const hasCitation = CITATION.test(line);
      CITATION.lastIndex = 0;
      if (!hasCitation && !NA.test(line)) {
        errors.push(`${label}: dimension "${dim}" is checked but has no path:line citation and is not marked "N/A — reason"`);
      }
    }
  }

  // Citation resolution (grounding mode only).
  if (mode === 'grounding') {
    let m;
    CITATION.lastIndex = 0;
    while ((m = CITATION.exec(scanned)) !== null) {
      const [, rel, lineStr] = m;
      const abs = path.join(ctx.repoRoot, rel);
      if (!existsSync(abs)) {
        errors.push(`${label}: ungrounded citation — path does not exist: ${rel}:${lineStr}`);
        continue;
      }
      // Stale line number → warning (not fail).
      try {
        const count = readFileSync(abs, 'utf8').split('\n').length;
        if (parseInt(lineStr, 10) > count) {
          warnings.push(`${label}: stale citation line ${rel}:${lineStr} (file has ${count} lines)`);
        }
      } catch { /* unreadable but exists — leave as pass */ }
    }
  }

  return { ok: errors.length === 0, errors, warnings };
}

/**
 * Which staged paths are plans the gate must validate: `.md` under any `plan.dirs` value, EXCLUDING
 * the configured `plan.claimsFile` — the orchestration claims ledger lives in a plan dir but is not a
 * plan (it ships no code). Pure (no git) so it is unit-testable. Adopters without a `claimsFile` get
 * no exclusion → identical behavior. Only the automatic sweep is scoped; explicit `--file` is untouched.
 */
export function selectPlanPaths(paths, config) {
  const planDirs = Object.values(config.plan?.dirs || {});
  const claims = config.plan?.claimsFile ? path.normalize(config.plan.claimsFile) : null;
  return paths.filter((p) =>
    planDirs.some((d) => p.startsWith(d)) &&
    p.endsWith('.md') &&
    (claims === null || path.normalize(p) !== claims)
  );
}

/** CLI: check staged plan files, or a --file. Exit 1 on any error. */
export function main(argv) {
  const root = gitRoot();
  const config = loadConfig(root);
  const fileFlag = (() => { const i = argv.indexOf('--file'); return i >= 0 ? argv[i + 1] : null; })();

  const planPaths = fileFlag ? [fileFlag] : selectPlanPaths(stagedPaths(), config);

  if (planPaths.length === 0) return 0; // nothing to check

  let ok = true;
  for (const rel of planPaths) {
    const content = fileFlag ? (existsSync(rel) ? readFileSync(rel, 'utf8') : '') : (readRepoFile(root, rel) || '');
    const res = checkPlanEvidence(content, { repoRoot: root, config, fileLabel: rel });
    for (const w of res.warnings) console.error(`! ${w}`);
    for (const e of res.errors) console.error(`✗ ${e}`);
    if (!res.ok) ok = false;
  }
  if (ok) console.log(`✓ plan-evidence: ${planPaths.length} plan(s) grounded`);
  return ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
