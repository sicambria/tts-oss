#!/usr/bin/env node
/**
 * @description SOTA capability-coverage scorecard (0–1000). Scores this harness against the
 * field-derived 11-aspect weighted rubric (src: research/harness-research-data.json). Grading is
 * MOSTLY PRESENCE, PARTLY HEALTH — be precise about which: of 43 checks, 35 are presence proxies
 * `[P]` that earn FULL credit (grade 1) on mere presence (several are count-bucketed, so a padded
 * dir CAN inflate them), and only 8 are health-verified `[H]` that grade via doctor.mjs — full
 * credit only when doctor reports the capability wired-and-healthy, 0.5 on a doctor WARN, 0 on
 * FAIL/absent (`clampGrade` below). So the anti-gaming guarantee is real but PARTIAL: the 8 `[H]`
 * checks (an uncommitted memory.md, an unwired hook, a broken canary, an unfilled verify contract)
 * resist gaming; the 35 `[P]` presence/count proxies do not. This is a capability-COVERAGE
 * self-portrait ("how many SOTA-harness capabilities are present, a handful health-verified"), NOT
 * an efficacy measure.
 *
 * IMPORTANT — what this score is and is NOT: capability-coverage on THIS repo, NOT a benchmark-
 * measured performance SOTA position, and NOT a validated cross-harness ranking against the printed
 * ANCHORS (those are hand-assigned expert judgments on a DIFFERENT construct — see BENCHMARK_NOTE).
 * Measured performance SOTA lives in research/SOTA/ (resolve-rate/cost benchmarks). The output
 * banner + the `[P]`/`[H]` legend keep the views from being conflated.
 *
 * Pure core (`scoreSota`, `bandFor`, `freshSnapshot`) is unit-testable on synthetic snapshots;
 * `collectSnapshot` reads the real tree (fs + git + config + doctor.runChecks) and never throws.
 * Advisory by default (exit 0); `--min <n>` opts into gating; `--json` for machines; `--write`
 * persists a snapshot to the observability spine; `--fresh` scores the ADOPTER FLOOR (neutralizes
 * dogfood corpus-population probes to fresh-`kaizen init` values). Output reports RELATIVE paths
 * only (identity-gate clean).
 *
 *   node .harness/scripts/ops/sota-score.mjs            # human scorecard (exit 0)
 *   node .harness/scripts/ops/sota-score.mjs --json     # machine-readable
 *   node .harness/scripts/ops/sota-score.mjs --write    # + persist .harness/state/sota-score.json
 *   node .harness/scripts/ops/sota-score.mjs --fresh    # adopter floor (fresh-init, dogfood-neutral)
 *   node .harness/scripts/ops/sota-score.mjs --min 700  # exit 1 if total < 700
 */
import { existsSync, readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot, git } from '../lib/repo.mjs';
import { loadConfig } from '../lib/config.mjs';
import { logEvent } from './events.mjs';
import { runChecks } from '../doctor.mjs';

// ── Calibration anchors (src: research/AI-Harness-Research-Report.md — weighted composite 0–1000) ──
export const ANCHORS = [
  { name: 'GSD Core (study top)', score: 858 },
  { name: 'changemappers', score: 760 },
  { name: 'study median (11 harnesses)', score: 693 },
];

// ── Honest-framing banner (src: research/SOTA/README.md) ──
export const BENCHMARK_NOTE =
  'This is a HARNESS CAPABILITY-COVERAGE score — how many SOTA-harness capabilities are present in ' +
  'this repo (~81% presence-graded [P], only 8/43 checks health-verified [H] via doctor). It is NOT ' +
  'a benchmark-measured performance SOTA position. For measured performance SOTA see research/SOTA/: ' +
  'decontaminated SWE-bench-Verified-class resolve ≈60–77%, Terminal-Bench 2.0 (outcome-verified), ' +
  'cost-per-task as a first-class axis. (Frontier ~95% numbers are contamination-inflated — see ' +
  'research/SOTA §6.) The printed ANCHORS are hand-assigned expert judgments (LLM-scored study ' +
  'estimates, ±40 noise) on a DIFFERENT construct measured differently — so placing this number ' +
  'beside them is NOT a validated cross-harness ranking.';

// ── Bands (0–1000) ──
export const BANDS = [
  { min: 850, label: 'SOTA' },
  { min: 700, label: 'strong (near-SOTA)' },
  { min: 500, label: 'solid' },
  { min: 300, label: 'developing' },
  { min: 0, label: 'nascent' },
];
export function bandFor(total) {
  return (BANDS.find((b) => total >= b.min) || BANDS[BANDS.length - 1]).label;
}

// ── The rubric: 11 aspects, weights verbatim from research/harness-research-data.json. Each check
//    has an `id` (a grade in {0,0.5,1} keyed in snapshot.signals), `points` (intra-aspect weight),
//    and `kind`: 'H' = health-verified via doctor, 'P' = presence (weaker signal, labeled as such).
export const RUBRIC = [
  { slug: 'agnosticism', name: 'Provider/model/tool agnosticism', weight: 1.0, checks: [
    { id: 'agn.canonical', label: 'AGENTS.md canonical contract', points: 3, kind: 'P' },
    { id: 'agn.overlays', label: 'agent overlays import the contract', points: 2, kind: 'P' },
    { id: 'agn.templates', label: 'templates/ adapters present', points: 2, kind: 'P' },
  ] },
  { slug: 'maturity', name: 'Maturity & adoption', weight: 0.8, checks: [
    { id: 'mat.tests', label: 'test suite size (coarse proxy)', points: 3, kind: 'P' },
    { id: 'mat.changelog', label: 'CHANGELOG.md', points: 1, kind: 'P' },
    { id: 'mat.readme', label: 'README.md', points: 1, kind: 'P' },
    { id: 'mat.pkg', label: 'package.json', points: 1, kind: 'P' },
  ] },
  { slug: 'memory', name: 'Memory & context engineering', weight: 1.0, checks: [
    { id: 'mem.committed', label: 'memory committed in-repo (doctor)', points: 3, kind: 'H' },
    { id: 'mem.nonempty', label: 'hot memory non-empty', points: 2, kind: 'P' },
    { id: 'mem.episodic', label: 'episodic memory dir', points: 1, kind: 'P' },
    { id: 'mem.rules', label: 'behavioral rules file', points: 1, kind: 'P' },
    { id: 'mem.hook', label: 'memory-capture hook', points: 1, kind: 'P' },
  ] },
  { slug: 'planning', name: 'Planning & spec discipline', weight: 1.0, checks: [
    { id: 'plan.gate', label: 'plan-evidence gate', points: 3, kind: 'P' },
    { id: 'plan.config', label: 'plan config (evidenceHeading + planTypes)', points: 2, kind: 'P' },
    { id: 'plan.file', label: 'a plan carries the evidence heading', points: 1, kind: 'P' },
  ] },
  { slug: 'orchestration', name: 'Workflow orchestration', weight: 1.0, checks: [
    { id: 'orch.gatemanifest', label: 'gate manifest present (doctor)', points: 2, kind: 'H' },
    { id: 'orch.nextgate', label: 'phase-gate orchestrator', points: 2, kind: 'P' },
    { id: 'orch.scaffold', label: 'scaffolder present', points: 1, kind: 'P' },
  ] },
  { slug: 'guardrails', name: 'Guardrails & safety', weight: 1.0, checks: [
    { id: 'guard.hooks', label: 'hooks wired & kaizen-managed (doctor)', points: 3, kind: 'H' },
    { id: 'guard.session', label: 'guard-session config sane (doctor)', points: 1, kind: 'H' },
    { id: 'guard.branchguard', label: 'branch-guard lib', points: 1, kind: 'P' },
    { id: 'guard.invariants', label: 'INVARIANTS registry', points: 1, kind: 'P' },
  ] },
  { slug: 'verification', name: 'Verification & testing loops', weight: 1.0, checks: [
    { id: 'ver.contract', label: 'verify contract filled (doctor)', points: 2, kind: 'H' },
    { id: 'ver.realcmds', label: 'verify has real (non-N/A) commands', points: 2, kind: 'P' },
    { id: 'ver.audits', label: 'audit gate count', points: 2, kind: 'P' },
    { id: 'ver.canary', label: 'contract-read canary intact (doctor)', points: 1, kind: 'H' },
    { id: 'ver.verifyjs', label: 'verify runner', points: 1, kind: 'P' },
  ] },
  { slug: 'extensibility', name: 'Extensibility & integrations', weight: 0.9, checks: [
    { id: 'ext.templates', label: 'templates/ tree', points: 2, kind: 'P' },
    { id: 'ext.profiles', label: 'profile support (scientific)', points: 1, kind: 'P' },
    { id: 'ext.seam', label: 'ENV/config seams', points: 1, kind: 'P' },
  ] },
  { slug: 'observability', name: 'Observability, audit & cost', weight: 0.8, checks: [
    { id: 'obs.spine', label: 'event spine (ops/events)', points: 2, kind: 'P' },
    { id: 'obs.events', label: 'events.jsonl exists & parses', points: 1, kind: 'H' },
    { id: 'obs.circuit', label: 'circuit-breaker', points: 1, kind: 'P' },
    { id: 'obs.statusline', label: 'statusline', points: 1, kind: 'P' },
  ] },
  { slug: 'dx', name: 'DX, docs & onboarding', weight: 0.7, checks: [
    { id: 'dx.readme', label: 'README.md', points: 1, kind: 'P' },
    { id: 'dx.agents', label: 'AGENTS.md', points: 1, kind: 'P' },
    { id: 'dx.docs', label: 'docs/ tree', points: 1, kind: 'P' },
    { id: 'dx.claude', label: 'CLAUDE.md overlay', points: 1, kind: 'P' },
    { id: 'dx.doctorfix', label: 'doctor --fix repairs', points: 1, kind: 'P' },
  ] },
  { slug: 'governance', name: 'Governance & security', weight: 0.8, checks: [
    { id: 'gov.secrets', label: 'secret scanner status (doctor)', points: 2, kind: 'H' },
    { id: 'gov.identity', label: 'identity/fingerprint gate', points: 1, kind: 'P' },
    { id: 'gov.decisionlog', label: 'decision-log gate', points: 1, kind: 'P' },
    { id: 'gov.license', label: 'LICENSE', points: 1, kind: 'P' },
  ] },
];

// The doctor OK/WARN/FAIL message substrings the health grades match on. Exported so a coupling test
// can assert doctor still emits each one — a rename fails loudly instead of silently degrading a grade.
export const DOCTOR_SIGNALS = [
  'hooks wired via core.hooksPath',
  'verify contract filled',
  'gate manifest present',
  'contract-read canary',
  'memory committed',
  'secret scann',
];

/**
 * Pure scoring. `snapshot.signals` maps checkId → grade in {0,0.5,1}; `snapshot.evidence` maps
 * checkId → short human string. Missing signal ⇒ 0. Deterministic; no I/O; time-independent.
 * @returns {{total:number, band:string, anchors:typeof ANCHORS, benchmarkNote:string, aspects:Array}}
 */
export function scoreSota(snapshot) {
  const signals = (snapshot && snapshot.signals) || {};
  const evidence = (snapshot && snapshot.evidence) || {};
  let wsum = 0;
  let wtotal = 0;
  const aspects = RUBRIC.map((a) => {
    let earned = 0;
    let possible = 0;
    const checks = a.checks.map((c) => {
      const grade = clampGrade(signals[c.id]);
      earned += grade * c.points;
      possible += c.points;
      return { id: c.id, label: c.label, kind: c.kind, points: c.points, grade,
        evidence: evidence[c.id] || (grade === 1 ? 'present' : grade === 0.5 ? 'partial' : 'absent') };
    });
    const score = possible ? Math.round((1000 * earned) / possible) : 0;
    wsum += score * a.weight;
    wtotal += a.weight;
    return { slug: a.slug, name: a.name, weight: a.weight, score, checks };
  });
  const total = wtotal ? Math.round(wsum / wtotal) : 0;
  return { total, band: bandFor(total), anchors: ANCHORS, benchmarkNote: BENCHMARK_NOTE, aspects };
}

function clampGrade(g) {
  const n = Number(g);
  if (!Number.isFinite(n) || n <= 0) return 0;
  if (n >= 1) return 1;
  return 0.5;
}

/**
 * The dogfood corpus-population probes — signals that score 1 ONLY because this is the long-lived
 * AUTHORING repo, not because a capability is installed. A fresh `kaizen init` adopter has none of
 * this accumulated corpus. Values here are what a fresh adopter would realistically have.
 * Deliberately EXCLUDES the 8 `[H]` health checks and the structural presence probes — a fresh
 * adopter installs those (they reflect wiring, not accumulated history).
 */
export const FRESH_DOGFOOD_SIGNALS = {
  'mat.tests': 0, //     no accumulated kaizen dogfood test corpus (this repo's 300+ tests are dogfood)
  'mem.nonempty': 0.5, // memory ships as a thin template stub, not populated real content
  'mem.episodic': 0, //   no episodic journals accumulated yet
  'obs.events': 0.5, //   event spine present, no data logged yet (matches eventsGrade's absent→0.5)
  'plan.file': 0, //      no authored plan carries the evidence heading yet
};

/**
 * Adopter-floor transform (#6). Returns a NEW snapshot — never mutates its input — with the dogfood
 * corpus-population signals neutralized to fresh-adopter values, so `scoreSota(freshSnapshot(snap))`
 * reports the floor a freshly-`kaizen init`ed repo would score. The `scoreSota`/`clampGrade` math is
 * untouched; only the input signals change. Feed the result to `scoreSota` unchanged.
 */
export function freshSnapshot(snapshot) {
  const signals = { ...((snapshot && snapshot.signals) || {}) };
  const evidence = { ...((snapshot && snapshot.evidence) || {}) };
  for (const [id, grade] of Object.entries(FRESH_DOGFOOD_SIGNALS)) {
    signals[id] = grade;
    const was = (snapshot && snapshot.evidence && snapshot.evidence[id]) || '';
    evidence[id] = `fresh-adopter floor (dogfood-neutralized)${was ? ` — was: ${was}` : ''}`;
  }
  return { ...snapshot, signals, evidence };
}

// ───────────────────────────── real-tree probes (CLI side, never throws) ─────────────────────────

const has = (root, rel) => { try { return existsSync(path.join(root, rel)); } catch { return false; } };
const read = (root, rel) => { try { return readFileSync(path.join(root, rel), 'utf8'); } catch { return ''; } };
const list = (root, rel) => { try { return readdirSync(path.join(root, rel)); } catch { return []; } };

/** doctor grade: OK-match → 1, WARN-match → 0.5, else 0. */
function dg(doc, needle) {
  if ((doc.oks || []).some((m) => m.includes(needle))) return 1;
  if ((doc.warns || []).some((m) => m.includes(needle))) return 0.5;
  return 0;
}
/** three-way bucketed grade for a count. */
function bucket(n, hi, mid) { return n >= hi ? 1 : n >= mid ? 0.5 : 0; }

/**
 * Read the real tree into a {signals, evidence, doctor, meta} snapshot. Folds in doctor.runChecks so
 * health-verified checks grade on wired-and-working. Wrapped defensively — always returns a snapshot.
 */
export function collectSnapshot(root) {
  let doc = { oks: [], warns: [], fails: [] };
  try { doc = runChecks(root, loadConfig(root)); } catch { /* doctor unavailable → all H grades 0 */ }
  let cfg = {};
  try { cfg = loadConfig(root); } catch { /* no config → plan/verify config grades 0 */ }

  const signals = {};
  const evidence = {};
  const set = (id, grade, ev) => { signals[id] = grade; evidence[id] = ev; };

  // agnosticism
  set('agn.canonical', has(root, 'AGENTS.md') ? 1 : 0, 'AGENTS.md');
  const claude = read(root, 'CLAUDE.md');
  set('agn.overlays', claude.includes('AGENTS.md') ? 1 : claude ? 0.5 : 0,
    claude.includes('AGENTS.md') ? 'CLAUDE.md imports AGENTS.md' : claude ? 'CLAUDE.md present, no contract ref' : 'no overlay');
  set('agn.templates', has(root, 'templates/core') ? 1 : 0, 'templates/core');

  // maturity
  const tests = list(root, 'test').filter((f) => f.endsWith('.test.mjs')).length;
  set('mat.tests', bucket(tests, 20, 5), `${tests} *.test.mjs (coarse presence proxy)`);
  set('mat.changelog', has(root, 'CHANGELOG.md') ? 1 : 0, 'CHANGELOG.md');
  set('mat.readme', has(root, 'README.md') ? 1 : 0, 'README.md');
  set('mat.pkg', has(root, 'package.json') ? 1 : 0, 'package.json');

  // memory
  set('mem.committed', dg(doc, 'memory committed'),
    dg(doc, 'memory committed') === 1 ? 'doctor: committed in-repo' : 'doctor: not committed/absent');
  const mem = read(root, '.harness/memory/memory.md');
  set('mem.nonempty', mem.trim().length > 200 ? 1 : mem ? 0.5 : 0,
    mem.trim().length > 200 ? 'hot memory populated' : mem ? 'hot memory thin' : 'no hot memory');
  set('mem.episodic', has(root, '.harness/memory/episodic') ? 1 : 0, '.harness/memory/episodic/');
  set('mem.rules', has(root, '.harness/memory/rules.md') ? 1 : 0, '.harness/memory/rules.md');
  set('mem.hook', has(root, '.harness/scripts/memory-capture.mjs') ? 1 : 0, 'memory-capture.mjs');

  // planning
  set('plan.gate', has(root, '.harness/scripts/audits/verify-plan-evidence.mjs') ? 1 : 0, 'verify-plan-evidence.mjs');
  const heading = cfg.plan?.evidenceHeading;
  const planTypes = Array.isArray(cfg.plan?.planTypes) ? cfg.plan.planTypes.length : 0;
  set('plan.config', heading && planTypes ? 1 : heading || planTypes ? 0.5 : 0,
    `evidenceHeading=${heading ? 'set' : 'unset'}, planTypes=${planTypes}`);
  const planDir = cfg.plan?.dirs?.active || 'docs/plans';
  let planWithHeading = 0;
  let planCount = 0;
  for (const dir of [planDir, cfg.plan?.dirs?.done].filter(Boolean)) {
    for (const f of list(root, dir).filter((x) => x.endsWith('.md'))) {
      planCount++;
      if (heading && read(root, path.join(dir, f)).includes(heading)) planWithHeading++;
    }
  }
  set('plan.file', planWithHeading ? 1 : planCount ? 0.5 : 0,
    `${planWithHeading}/${planCount} plan(s) carry the evidence heading`);

  // orchestration
  set('orch.gatemanifest', dg(doc, 'gate manifest present'), 'doctor: gate manifest');
  set('orch.nextgate', has(root, '.harness/scripts/next-phase-gate.mjs') ? 1 : 0, 'next-phase-gate.mjs');
  set('orch.scaffold', has(root, '.harness/scripts/scaffold.mjs') ? 1 : 0, 'scaffold.mjs');

  // guardrails
  set('guard.hooks', dg(doc, 'hooks wired via core.hooksPath'), 'doctor: hooks wired+executable+managed');
  const guardSane = (doc.oks || []).some((m) => m.includes('guard-session config sane') || m.includes('guard session active')) ? 1 : 0;
  set('guard.session', guardSane, 'doctor: guard-session config');
  set('guard.branchguard', has(root, '.harness/scripts/lib/branch-guard.mjs') ? 1 : 0, 'lib/branch-guard.mjs');
  set('guard.invariants', has(root, '.harness/INVARIANTS.md') ? 1 : 0, '.harness/INVARIANTS.md');

  // verification
  set('ver.contract', dg(doc, 'verify contract filled'), 'doctor: verify contract filled');
  const v = cfg.verify || {};
  const realCmds = ['test', 'lint', 'build', 'e2e', 'healthcheck']
    .filter((k) => v[k] && String(v[k]).trim() && String(v[k]).trim().toUpperCase() !== 'N/A').length;
  set('ver.realcmds', bucket(realCmds, 2, 1), `${realCmds} real (non-N/A) verify command(s)`);
  const audits = list(root, '.harness/scripts/audits').filter((f) => f.endsWith('.mjs')).length;
  set('ver.audits', bucket(audits, 6, 3), `${audits} audit gate(s)`);
  set('ver.canary', dg(doc, 'contract-read canary'), 'doctor: canary intact');
  set('ver.verifyjs', has(root, '.harness/scripts/verify.mjs') ? 1 : 0, 'verify.mjs');

  // extensibility
  set('ext.templates', has(root, 'templates') ? 1 : 0, 'templates/');
  set('ext.profiles', has(root, 'templates/profiles/scientific') ? 1 : 0, 'templates/profiles/scientific');
  const seam = read(root, '.harness/scripts/audits/verify-identity.mjs').includes('seam(')
    || read(root, '.harness/scripts/lib/config.mjs').includes('export function seam');
  set('ext.seam', seam ? 1 : 0, 'config/ENV seams');

  // observability
  set('obs.spine', has(root, '.harness/scripts/ops/events.mjs') ? 1 : 0, 'ops/events.mjs');
  set('obs.events', eventsGrade(root), 'events.jsonl parse');
  set('obs.circuit', has(root, '.harness/scripts/ops/circuit-breaker.mjs') ? 1 : 0, 'ops/circuit-breaker.mjs');
  set('obs.statusline', has(root, '.harness/scripts/ops/statusline.mjs') ? 1 : 0, 'ops/statusline.mjs');

  // dx
  set('dx.readme', has(root, 'README.md') ? 1 : 0, 'README.md');
  set('dx.agents', has(root, 'AGENTS.md') ? 1 : 0, 'AGENTS.md');
  set('dx.docs', has(root, 'docs') ? 1 : 0, 'docs/');
  set('dx.claude', has(root, 'CLAUDE.md') ? 1 : 0, 'CLAUDE.md');
  set('dx.doctorfix', read(root, '.harness/scripts/doctor.mjs').includes('--fix') ? 1 : 0, 'doctor --fix');

  // governance
  set('gov.secrets', dg(doc, 'secret scann'), 'doctor: secret scanner status');
  set('gov.identity', has(root, '.harness/scripts/audits/verify-identity.mjs') ? 1 : 0, 'verify-identity.mjs');
  set('gov.decisionlog', has(root, '.harness/scripts/audits/verify-decision-log.mjs') ? 1 : 0, 'verify-decision-log.mjs');
  set('gov.license', has(root, 'LICENSE') ? 1 : 0, 'LICENSE');

  return { signals, evidence, doctor: doc, meta: { tests, audits, realCmds } };
}

/** events.jsonl: exists & every line parses → 1; exists with a parse error → 0; absent → 0.5 (spine present, no data). */
function eventsGrade(root) {
  const p = '.harness/state/events.jsonl';
  if (!has(root, p)) return 0.5;
  const body = read(root, p).trim();
  if (!body) return 0.5;
  for (const line of body.split('\n')) {
    try { JSON.parse(line); } catch { return 0; }
  }
  return 1;
}

// ───────────────────────────────────────── CLI ──────────────────────────────────────────────────

function grade(g) { return g === 1 ? '✓' : g === 0.5 ? '~' : '✗'; }

export function renderHuman(result, opts = {}) {
  const fresh = opts.mode === 'fresh';
  const lines = [];
  lines.push('SOTA capability-coverage scorecard' + (fresh ? '  [--fresh: adopter floor]' : ''));
  lines.push('─'.repeat(72));
  for (const line of wrap(result.benchmarkNote, 72)) lines.push(line);
  lines.push('legend: [P] = presence proxy (not efficacy) · [H] = health-verified via doctor');
  if (fresh) {
    for (const line of wrap('adopter floor: dogfood corpus-population probes (accumulated tests / ' +
      'hot-memory content / episodic journals / event log / authored plans) are neutralized to ' +
      `fresh-\`kaizen init\` values. The dogfood ceiling on THIS authoring repo is ${opts.ceiling}/1000 ` +
      '— a saturated reference, not a floor.', 72)) lines.push(line);
  }
  lines.push('─'.repeat(72));
  for (const a of result.aspects) {
    lines.push(`${String(a.score).padStart(4)}/1000  ${a.name}  (w${a.weight})`);
    for (const c of a.checks) {
      lines.push(`         ${grade(c.grade)} [${c.kind}] ${c.label} — ${c.evidence}`);
    }
  }
  lines.push('─'.repeat(72));
  lines.push(`TOTAL: ${result.total}/1000 — ${result.band}` +
    (fresh ? `  (adopter floor — dogfood ceiling ${opts.ceiling}/1000)` : ''));
  lines.push(`anchors: ${result.anchors.map((a) => `${a.name} ${a.score}`).join(' · ')}`);
  lines.push('  ↑ hand-assigned expert judgments on a different construct (±40 noise) — a placement ' +
    'reference, NOT a validated cross-harness ranking.');
  return lines.join('\n');
}

function wrap(s, w) {
  const out = [];
  let cur = '';
  for (const word of s.split(/\s+/)) {
    if ((cur + ' ' + word).trim().length > w) { out.push(cur.trim()); cur = word; }
    else cur += ' ' + word;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

export function main(argv) {
  const root = gitRoot();
  const snapshot = collectSnapshot(root);
  const fresh = argv.includes('--fresh');
  // Compute the pristine (dogfood) score FIRST from the untouched snapshot — it is the ceiling
  // reference in --fresh mode, and the default result otherwise. freshSnapshot never mutates input.
  const dogfoodResult = scoreSota(snapshot);
  const result = fresh ? scoreSota(freshSnapshot(snapshot)) : dogfoodResult;
  const ceiling = dogfoodResult.total;
  // In --fresh mode the persisted/emitted payload carries the mode + ceiling; the DEFAULT payload is
  // byte-for-byte the same shape as before (no added keys) so nothing downstream drifts.
  const payload = fresh ? { ...result, mode: 'fresh', dogfoodCeiling: ceiling } : result;

  if (argv.includes('--json')) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.log(renderHuman(result, fresh ? { mode: 'fresh', ceiling } : {}));
  }

  if (argv.includes('--write')) {
    try {
      const dir = path.join(root, '.harness', 'state');
      if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
      writeFileSync(path.join(dir, 'sota-score.json'), JSON.stringify(payload, null, 2) + '\n');
      logEvent(root, fresh
        ? { type: 'sota_score', total: result.total, band: result.band, mode: 'fresh', dogfoodCeiling: ceiling }
        : { type: 'sota_score', total: result.total, band: result.band });
    } catch { /* persistence is best-effort; never fail the assessment on a write error */ }
  }

  const minIdx = argv.indexOf('--min');
  if (minIdx !== -1) {
    const min = Number(argv[minIdx + 1]);
    if (Number.isFinite(min) && result.total < min) {
      console.error(`\n✗ sota-score: ${result.total} < --min ${min}`);
      return 1;
    }
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
