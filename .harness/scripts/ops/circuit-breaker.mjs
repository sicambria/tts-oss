#!/usr/bin/env node
/**
 * @description L6 — live, observation-only circuit breaker (src: Liza). kaizen's learning loop is
 * post-hoc (a postmortem after a bug); this is the live complement: it reads the observability event
 * log and surfaces SYSTEMIC failure patterns — a retry cluster, an assumption cascade across tasks, a
 * repeated workaround — as a typed evidence report for a HUMAN to judge.
 *
 * OBSERVATION-ONLY, by hard rule (mirrors kaizen's fail-closed / no-silent-action stance): it never
 * proposes or applies a fix, and the CLI ALWAYS exits 0 — a breaker that blocked the pipeline would be
 * an actuator, and kaizen's actuators are the gate chain, not a heuristic over runtime telemetry.
 *
 * The emit side (the "events.jsonl wiring") is the contract: when a stop-trigger fires, the agent logs
 *   node .harness/scripts/ops/events.mjs --type anomaly --kind <trigger> [--task <id>]
 * (see `.harness/memory/rules.md`). The detector below only aggregates what has been logged — it cannot
 * see anomalies nobody recorded. That ceiling is stated in the plan and inherited from Liza.
 *
 * Pure core (`detectAnomalies`) + a thin CLI that reads `.harness/state/events.jsonl` via `readEvents`.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { readEvents } from './events.mjs';

/** Tunable trip thresholds. A caller may override any field. */
export const DEFAULT_THRESHOLDS = {
  /** N occurrences of the SAME anomaly kind → a repeating (architectural) pattern. */
  repeatCount: 3,
  /** Distinct tasks an assumption must be violated across → a spec-level (not local) flaw. */
  assumptionTasks: 2,
  /** Repeated workarounds/suppressions → the symptom-not-cause pattern. */
  workaroundCount: 2,
};

/** Anomaly kinds treated as assumption violations / workarounds (the two specifically-typed patterns). */
const ASSUMPTION_KINDS = new Set(['assumption-violation', 'assumption-cascade']);
const WORKAROUND_KINDS = new Set(['workaround', 'suppression', 'symptom-fix']);

/**
 * Detect systemic anomaly patterns in a list of events. Pure + total: tolerates events missing any
 * field (never throws — observability must never block the critical path).
 * @param {Array<Record<string, unknown>>} events  (already-parsed; malformed lines are dropped upstream by readEvents)
 * @param {Partial<typeof DEFAULT_THRESHOLDS>} [thresholds]
 * @returns {Array<{ flaw: string, kind: string, count: number, tasks?: string[], detail: string }>}
 */
export function detectAnomalies(events, thresholds = {}) {
  const t = { ...DEFAULT_THRESHOLDS, ...thresholds };
  const list = Array.isArray(events) ? events : [];
  const anomalies = list.filter((e) => e && e.type === 'anomaly');

  const byKind = new Map(); // kind → { count, tasks:Set }
  for (const e of anomalies) {
    const kind = typeof e.kind === 'string' && e.kind ? e.kind : 'unspecified';
    const rec = byKind.get(kind) || { count: 0, tasks: new Set() };
    rec.count += 1;
    if (typeof e.task === 'string' && e.task) rec.tasks.add(e.task);
    byKind.set(kind, rec);
  }

  const findings = [];
  for (const [kind, rec] of byKind) {
    // Rule A — assumption violated across ≥N distinct tasks → SPEC_FLAW (not a local slip; the spec is wrong).
    if (ASSUMPTION_KINDS.has(kind) && rec.tasks.size >= t.assumptionTasks) {
      findings.push({
        flaw: 'SPEC_FLAW',
        kind,
        count: rec.count,
        tasks: [...rec.tasks],
        detail: `assumption "${kind}" violated across ${rec.tasks.size} tasks (≥${t.assumptionTasks}) — presume the framing/spec is wrong`,
      });
      continue; // specifically typed; don't also count it as a generic repeat
    }
    // Rule B — repeated workaround/suppression → WORKAROUND_REPEAT (symptom-not-cause pattern).
    if (WORKAROUND_KINDS.has(kind) && rec.count >= t.workaroundCount) {
      findings.push({
        flaw: 'WORKAROUND_REPEAT',
        kind,
        count: rec.count,
        detail: `"${kind}" logged ${rec.count}× (≥${t.workaroundCount}) — recurring workaround, fix the root cause`,
      });
      continue;
    }
    // Rule C — any other anomaly kind repeated ≥N times → ARCHITECTURE_FLAW (a retry/step-repetition cluster).
    if (rec.count >= t.repeatCount) {
      findings.push({
        flaw: 'ARCHITECTURE_FLAW',
        kind,
        count: rec.count,
        detail: `"${kind}" repeated ${rec.count}× (≥${t.repeatCount}) — a systemic pattern, not a one-off`,
      });
    }
  }
  return findings;
}

/** Render a human-facing evidence report. Observation-only — it recommends a human review, never a fix. */
export function renderReport(findings, totalAnomalies) {
  if (!findings.length) {
    return `○ circuit-breaker: no systemic pattern (${totalAnomalies} anomaly event(s) below all thresholds)`;
  }
  const lines = [`⚠ circuit-breaker TRIPPED — ${findings.length} systemic pattern(s). Observation-only: a HUMAN decides.`];
  for (const f of findings) lines.push(`  [${f.flaw}] ${f.detail}`);
  lines.push('  → This is not an auto-fix. Review the evidence and rescope/repair at the human layer.');
  return lines.join('\n');
}

export function main() {
  const root = gitRoot();
  const events = readEvents(root);
  const anomalies = events.filter((e) => e && e.type === 'anomaly').length;
  const findings = detectAnomalies(events);
  console.log(renderReport(findings, anomalies));
  return 0; // ALWAYS 0 — observation-only, never blocks.
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
