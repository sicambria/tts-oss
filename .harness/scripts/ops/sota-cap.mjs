#!/usr/bin/env node
/**
 * @description Additive SOTA must-have cap (advisory transparency beside the score).
 * Takes an EXPLICIT versioned must-have slug list and reports the minimum score among
 * the required aspects plus the limiting aspect. It never changes scores, bands,
 * `--min`, gating, efficacy claims, or anchor presentation: unknown slug is an input
 * error, a measured zero is a valid cap, and an unassessed required aspect yields
 * `undetermined`. Imports the scorer's RUBRIC read-only; no scoring arithmetic lives
 * here and none in `sota-score.mjs` is touched. Changing the slug set later requires
 * a decision record because it changes interpretation.
 *
 * Pure core (`resolveMustHaves` / `computeCap`) + a thin advisory CLI.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RUBRIC, scoreSota, collectSnapshot } from './sota-score.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

export const CAP_VERSION = 'v1';

/** Versioned must-have slug sets. A new version is a deliberate interpretation change. */
export const MUST_HAVE_SETS = {
  v1: ['memory', 'planning', 'verification', 'guardrails'],
};

const KNOWN_SLUGS = () => RUBRIC.map((a) => a.slug);

/**
 * Resolve a must-have spec (version key like 'v1' or an explicit slug array) against
 * the rubric. Unknown slugs are input errors — never silently dropped.
 * @returns {{ok:boolean, slugs:string[], error:string|null, version:string}}
 */
export function resolveMustHaves(spec) {
  const known = KNOWN_SLUGS();
  let slugs;
  let version;
  if (typeof spec === 'string' && MUST_HAVE_SETS[spec]) {
    slugs = [...MUST_HAVE_SETS[spec]];
    version = spec;
  } else if (Array.isArray(spec)) {
    slugs = [...spec];
    version = 'explicit';
  } else {
    return { ok: false, slugs: [], error: `unknown must-have set "${spec}" (known versions: ${Object.keys(MUST_HAVE_SETS).join(', ')})`, version: 'invalid' };
  }
  const unknown = slugs.filter((s) => !known.includes(s));
  if (unknown.length) {
    return { ok: false, slugs, error: `unknown must-have slug(s): ${unknown.join(', ')} (known: ${known.join(', ')})`, version };
  }
  return { ok: true, slugs, error: null, version };
}

/**
 * Pure cap over an ALREADY-SCORED result (output of `scoreSota`). Never recomputes
 * scores — it only reads per-aspect scores. `assessed` lists the slugs actually
 * measured in this run; a required slug outside it yields `undetermined`.
 * A measured zero is a VALID cap (cap 0, limiting named).
 * @returns {{status:'capped'|'undetermined'|'error', cap:number|null, limiting:string|null, slugs:Array, assessed:Array, version:string, error:string|null}}
 */
export function computeCap(scoreResult, spec, assessed) {
  const resolved = resolveMustHaves(spec);
  if (!resolved.ok) {
    return { status: 'error', cap: null, limiting: null, slugs: [], assessed: assessed || [], version: resolved.version, error: resolved.error };
  }
  const assessedSet = new Set(Array.isArray(assessed) ? assessed : resolved.slugs);
  const bySlug = new Map((scoreResult.aspects || []).map((a) => [a.slug, a.score]));
  const missing = resolved.slugs.filter((s) => !assessedSet.has(s));
  if (missing.length) {
    return {
      status: 'undetermined', cap: null, limiting: null,
      slugs: resolved.slugs, assessed: [...assessedSet], version: resolved.version,
      error: null, unassessed: missing,
    };
  }
  let cap = Infinity;
  let limiting = null;
  for (const s of resolved.slugs) {
    const score = bySlug.has(s) ? bySlug.get(s) : 0;
    if (score < cap) { cap = score; limiting = s; }
  }
  return {
    status: 'capped', cap: cap === Infinity ? 0 : cap, limiting,
    slugs: resolved.slugs, assessed: [...assessedSet], version: resolved.version, error: null,
  };
}

/** Human + machine rendering of a cap result. */
export function renderCap(capResult, scoreResult) {
  if (capResult.status === 'error') return `must-have cap: input error — ${capResult.error}`;
  if (capResult.status === 'undetermined') {
    return `must-have cap (${capResult.version}): UNDETERMINED — unassessed required aspect(s): ${capResult.unassessed.join(', ')} (score ${scoreResult.total}/1000 unchanged)`;
  }
  return `must-have cap (${capResult.version}): ${capResult.cap}/1000 limited by "${capResult.limiting}" ` +
    `[${capResult.slugs.join(', ')}] (score ${scoreResult.total}/1000 unchanged — explanatory only)`;
}

/** CLI (advisory): prints the cap beside the score; never gates, never mutates scoring. */
export function main(argv) {
  const root = gitRoot();
  const si = argv.indexOf('--must-haves');
  const spec = si >= 0 && argv[si + 1] ? argv[si + 1] : CAP_VERSION;
  const snapshot = collectSnapshot(root);
  const result = scoreSota(snapshot);
  const assessed = RUBRIC.map((a) => a.slug);
  const cap = computeCap(result, MUST_HAVE_SETS[spec] ? spec : spec.split(','), assessed);
  if (argv.includes('--json')) {
    console.log(JSON.stringify({ ...result, mustHaveCap: cap }, null, 2));
  } else {
    console.log(renderCap(cap, result));
  }
  return cap.status === 'error' ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
