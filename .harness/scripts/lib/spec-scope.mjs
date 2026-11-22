#!/usr/bin/env node
/**
 * @description Spec-scope provenance report (pure parser/diff classifier, report-only).
 * Reports whether changed implementation, test, and script paths are declared by an
 * approved plan's scope block — traceability evidence, not a proof that code matches
 * prose. Scope block format inside the plan:
 *
 *   ## Approved Scope
 *   frozen-hash: <sha256 over the sorted newline-joined allowed list>
 *   allowed:
 *   - src/foo.ts
 *   - test/
 *
 * A trailing `/` marks a subtree prefix; otherwise a path matches exactly or as a
 * parent prefix (`src/foo` covers `src/foo/bar.ts`). Renames (`{from, to}`) classify
 * by their destination. Tests and scripts get no silent exemption. Malformed blocks
 * fail the report (never the build). This module never enters global verify.
 *
 * Pure core (`parseScopeBlock` / `freezeScope` / `classifyPaths` / `checkScope`) +
 * a thin advisory CLI.
 */
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

export const SCOPE_HEADING = '## Approved Scope';

/** Canonical hash over a scope's allowed list (sorted, newline-joined, trailing newline). */
export function freezeScope(allowed) {
  const canon = [...new Set((allowed || []).map((s) => String(s).trim()).filter(Boolean))].sort().join('\n') + '\n';
  return createHash('sha256').update(canon).digest('hex');
}

function extractScopeSection(content) {
  const lines = String(content || '').split('\n');
  const idx = lines.findIndex((l) => l.trim() === SCOPE_HEADING);
  if (idx === -1) return null;
  const out = [];
  for (let i = idx + 1; i < lines.length; i++) {
    if (/^#{1,2}\s/.test(lines[i])) break;
    out.push(lines[i]);
  }
  return out;
}

/**
 * Parse the approved scope block.
 * @returns {{ok:boolean, allowed:string[], hash:string|null, errors:string[]}}
 */
export function parseScopeBlock(planContent, fileLabel = 'plan') {
  const errors = [];
  const section = extractScopeSection(planContent);
  if (section == null) {
    return { ok: false, allowed: [], hash: null, errors: [`${fileLabel}: missing required section "${SCOPE_HEADING}"`] };
  }
  const hashLine = section.find((l) => /^\s*frozen-hash\s*:/i.test(l));
  const hash = hashLine ? hashLine.split(':')[1].trim() : null;
  if (!hash || !/^[0-9a-f]{64}$/i.test(hash)) {
    errors.push(`${fileLabel}: scope block has no valid frozen-hash (sha256 hex over the allowed list)`);
  }
  const allowedIdx = section.findIndex((l) => /^\s*allowed\s*:/i.test(l));
  const allowed = [];
  if (allowedIdx === -1) {
    errors.push(`${fileLabel}: scope block has no "allowed:" path list`);
  } else {
    for (let i = allowedIdx + 1; i < section.length; i++) {
      const m = section[i].match(/^\s*-\s+(\S+)\s*$/);
      if (!m) {
        if (section[i].trim() === '') continue;
        break; // end of the list
      }
      allowed.push(m[1]);
    }
    if (allowed.length === 0) errors.push(`${fileLabel}: scope block "allowed:" list is empty`);
  }
  return { ok: errors.length === 0, allowed, hash, errors };
}

/** Does `changed` fall inside `scopePath` (exact, parent-prefix, or trailing-slash subtree)? */
export function inScope(changed, scopePath) {
  const c = String(changed);
  const s = String(scopePath);
  if (c === s) return true;
  if (s.endsWith('/')) return c.startsWith(s);
  return c.startsWith(s + '/');
}

/**
 * Classify changed paths against an allowed list. Entries may be strings or
 * `{from, to}` renames (classified by destination, origin noted).
 * @returns {Array<{path:string, status:'declared'|'out-of-scope', via:string|null, renameFrom:string|null}>}
 */
export function classifyPaths(changedPaths, allowed) {
  const list = Array.isArray(changedPaths) ? changedPaths : [];
  return list.map((entry) => {
    const isRename = entry && typeof entry === 'object';
    const p = isRename ? String(entry.to || '') : String(entry);
    const via = (allowed || []).find((a) => inScope(p, a)) || null;
    return { path: p, status: via ? 'declared' : 'out-of-scope', via, renameFrom: isRename ? String(entry.from || '') : null };
  });
}

/**
 * Full report: parse + frozen-hash check + classification.
 * @returns {{ok:boolean, hashOk:boolean, classification:Array, errors:string[], warnings:string[]}}
 */
export function checkScope({ planContent, changedPaths, fileLabel = 'plan' } = {}) {
  const errors = [];
  const warnings = [];
  const parsed = parseScopeBlock(planContent, fileLabel);
  errors.push(...parsed.errors);
  let hashOk = false;
  if (parsed.hash && parsed.allowed.length) {
    hashOk = freezeScope(parsed.allowed).toLowerCase() === parsed.hash.toLowerCase();
    if (!hashOk) errors.push(`${fileLabel}: frozen-hash mismatch — the allowed list changed without a recorded revision (old/new hash + reason + approver required)`);
  }
  const classification = classifyPaths(changedPaths, parsed.allowed);
  const oos = classification.filter((c) => c.status === 'out-of-scope');
  if (oos.length) {
    warnings.push(`${fileLabel}: ${oos.length} changed path(s) outside the approved scope: ${oos.map((c) => c.path).join(', ')}`);
  }
  return { ok: errors.length === 0, hashOk, classification, errors, warnings };
}

/** Human-readable rendering of a scope report. */
export function formatScopeReport(result, fileLabel = 'plan') {
  const lines = [];
  lines.push(`spec-scope report for ${fileLabel} (advisory — not a gate)`);
  lines.push(`frozen-hash: ${result.hashOk ? 'intact' : 'MISMATCH/missing'}`);
  for (const c of result.classification) {
    const rename = c.renameFrom ? ` (renamed from ${c.renameFrom})` : '';
    lines.push(`  [${c.status}] ${c.path}${c.via ? ` via ${c.via}` : ''}${rename}`);
  }
  for (const w of [...result.errors, ...result.warnings]) lines.push(`! ${w}`);
  return lines.join('\n');
}

/** CLI (advisory): --plan <md> --changed <csv or @file>; renames as from=>to entries. */
export function main(argv) {
  const root = gitRoot();
  const pi = argv.indexOf('--plan');
  const ci = argv.indexOf('--changed');
  if (pi < 0 || !argv[pi + 1]) {
    console.error('usage: spec-scope.mjs --plan <plan.md> [--changed <a,b,from=>to>]');
    return 1;
  }
  const planFile = argv[pi + 1];
  const abs = path.isAbsolute(planFile) ? planFile : path.join(root, planFile);
  if (!existsSync(abs)) {
    console.error(`✗ spec-scope: plan not found: ${planFile}`);
    return 1;
  }
  const raw = ci >= 0 && argv[ci + 1] ? argv[ci + 1] : '';
  const changedPaths = raw ? raw.split(',').map((s) => {
    const m = s.trim().match(/^(.+)=>(.+)$/);
    return m ? { from: m[1].trim(), to: m[2].trim() } : s.trim();
  }).filter((s) => (typeof s === 'string' ? s : s.to)) : [];
  const res = checkScope({ planContent: readFileSync(abs, 'utf8'), changedPaths, fileLabel: planFile });
  console.log(formatScopeReport(res, planFile));
  // Report-only: exit 0 even with out-of-scope paths; exit 1 only on malformed blocks.
  return res.errors.length ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
