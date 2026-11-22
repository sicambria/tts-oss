#!/usr/bin/env node
/**
 * @description The `/next` phase gate — the ENFORCED state machine behind roadmap P0-2 (the
 * `/next` orchestration spine) and P1-6 (the Phase-1 pre-implementation gate). Progression runs
 * `plan → phase1 → analyze → approval → execute`; `advance` BLOCKS (exit 1) when a phase is
 * skipped OR the transition's required artifact is missing. Three artifact preconditions are real,
 * not nominal: `phase1` needs a plan file carrying the evidence heading, `approval` needs an
 * analyze report on disk, and `execute` needs a recorded human approval. State persists in
 * `.harness/state/next-state.json` (gitignored runtime state, per guard-session precedent).
 *
 * Pure core `canAdvance(state, target, artifacts)` (plain data, no I/O) + a thin CLI:
 *   next-phase-gate.mjs status
 *   next-phase-gate.mjs advance <phase> [--plan <path>] [--report <path>]
 *   next-phase-gate.mjs require <phase>
 *   next-phase-gate.mjs approve --by <who> [--note <text>]
 *   next-phase-gate.mjs reset
 *
 * The skills (`.claude/skills/next`, `.claude/skills/analyze`) and subagent role cards
 * (`.harness/subagents/*`) are SCAFFOLD that call this gate at each transition — this file is the
 * only thing that enforces.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from './lib/repo.mjs';

/** The ordered phase progression. Index position IS the ordering contract. */
export const PHASES = ['plan', 'phase1', 'analyze', 'approval', 'execute'];

/**
 * The artifact that must be present to advance INTO each phase (the output of the phase being
 * left). `plan` is the entry phase and requires nothing. Keys index into the resolved `artifacts`
 * object passed to `canAdvance`.
 */
export const REQUIRED_ARTIFACT = {
  plan: null,
  phase1: 'planFile', // a plan file with the evidence heading must exist (P1-6)
  analyze: 'planFile', // the plan must still resolve
  approval: 'analyzeReport', // /analyze must have produced a consistency report
  execute: 'approval', // a human approval must be on record
};

/** Human-readable description of each required artifact (for block messages). */
const ARTIFACT_DESC = {
  planFile: 'a plan file containing the evidence heading',
  analyzeReport: 'an /analyze consistency report',
  approval: 'a recorded human approval',
};

/**
 * Pure decision function. Given the current state and a resolved artifact map, decide whether
 * advancing to `target` is legal. No I/O, no process exit — directly unit-testable.
 * @param {{phase:(string|null)}|null} state  current state (`state.phase` = current phase or null).
 * @param {string} target  the phase to advance into.
 * @param {{planFile?:boolean, analyzeReport?:boolean, approval?:boolean}} artifacts  resolved facts.
 * @returns {{ok:boolean, reason?:string, from:(string|null), to:string, next:(string|null)}}
 */
export function canAdvance(state, target, artifacts = {}) {
  const current = state && typeof state.phase === 'string' ? state.phase : null;
  const next = current === null ? PHASES[0] : PHASES[PHASES.indexOf(current) + 1] || null;
  const base = { from: current, to: target, next };

  if (!PHASES.includes(target)) {
    return { ...base, ok: false, reason: `unknown phase '${target}' (expected one of: ${PHASES.join(', ')})` };
  }
  if (target === current) {
    return { ...base, ok: false, reason: `already at phase '${target}' — nothing to advance` };
  }
  if (target !== next) {
    // Out-of-order / skipped a phase. For `execute` specifically, name the approval precondition
    // so the block reads as the workflow intends ("must pass approval first").
    const tail = target === 'execute' ? ' — execute requires passing approval first' : '';
    return {
      ...base,
      ok: false,
      reason: `cannot advance to '${target}' from '${current ?? '(start)'}': must complete '${next}' first${tail}`,
    };
  }

  const need = REQUIRED_ARTIFACT[target];
  if (need && !artifacts[need]) {
    return {
      ...base,
      ok: false,
      reason: `cannot advance to '${target}': missing ${ARTIFACT_DESC[need] || need}`,
    };
  }
  return { ...base, ok: true };
}

// --- state I/O (CLI-side; the pure core above never touches disk) -----------------------------

/** Repo-relative path to the gitignored `/next` state file. */
export function statePath(root) {
  return path.join(root, '.harness', 'state', 'next-state.json');
}

/** Load state, or a fresh `{ phase: null }` if absent/malformed (disposable runtime state). */
export function loadState(root) {
  const p = statePath(root);
  if (!existsSync(p)) return { phase: null, history: [], approval: null, artifacts: {} };
  try {
    const parsed = JSON.parse(readFileSync(p, 'utf8'));
    if (!parsed || typeof parsed !== 'object') return { phase: null, history: [], approval: null, artifacts: {} };
    return {
      phase: typeof parsed.phase === 'string' ? parsed.phase : null,
      history: Array.isArray(parsed.history) ? parsed.history : [],
      approval: parsed.approval || null,
      artifacts: parsed.artifacts && typeof parsed.artifacts === 'object' ? parsed.artifacts : {},
    };
  } catch {
    return { phase: null, history: [], approval: null, artifacts: {} };
  }
}

function saveState(root, state) {
  const p = statePath(root);
  mkdirSync(path.dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(state, null, 2) + '\n');
}

// --- artifact resolution (CLI-side; keeps canAdvance pure) ------------------------------------

/**
 * Resolve the artifact map from state + disk. `planFile`/`analyzeReport` can be supplied fresh via
 * flags (path must resolve on disk) or persist from a prior transition recorded in state.
 * `approval` is read straight from recorded state.
 */
function resolveArtifacts(root, state, cfg, { plan, report } = {}) {
  const artifacts = { ...state.artifacts };

  if (plan !== undefined) {
    const abs = path.resolve(root, plan);
    const heading = (cfg.plan && cfg.plan.evidenceHeading) || '## Standards & Guardrails Evidence';
    // A plan file only counts if it exists AND carries the evidence heading — a bare stub is not
    // a plan (this is the P1-6 precondition that makes phase1 bite, not a nominal file check).
    artifacts.planFile = existsSync(abs) && readFileSafe(abs).includes(heading);
    artifacts.planPath = existsSync(abs) ? plan : null;
  }
  if (report !== undefined) {
    const abs = path.resolve(root, report);
    artifacts.analyzeReport = existsSync(abs);
    artifacts.analyzeReportPath = existsSync(abs) ? report : null;
  }
  artifacts.approval = Boolean(state.approval);
  return artifacts;
}

function readFileSafe(abs) {
  try { return readFileSync(abs, 'utf8'); } catch { return ''; }
}

// --- CLI --------------------------------------------------------------------------------------

function parseFlags(argv) {
  const flags = {};
  const pos = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      flags[key] = argv[i + 1] !== undefined && !argv[i + 1].startsWith('--') ? argv[++i] : true;
    } else pos.push(a);
  }
  return { flags, pos };
}

/** Best-effort event log — observability must never block the critical path. */
async function logTransition(root, fields) {
  try {
    const { logEvent } = await import('./ops/events.mjs');
    logEvent(root, fields);
  } catch { /* never throws */ }
}

export async function main(argv) {
  const { flags, pos } = parseFlags(argv);
  const cmd = pos[0];
  const root = gitRoot();

  if (cmd === 'status') {
    const state = loadState(root);
    const next = state.phase === null ? PHASES[0] : PHASES[PHASES.indexOf(state.phase) + 1] || '(none — execute is terminal)';
    console.log(`/next phase: ${state.phase ?? '(start)'}`);
    console.log(`  next allowed: ${next}`);
    console.log(`  artifacts: planFile=${Boolean(state.artifacts.planFile)} analyzeReport=${Boolean(state.artifacts.analyzeReport)} approval=${Boolean(state.approval)}`);
    if (state.approval) console.log(`  approved by: ${state.approval.by} @ ${state.approval.at}`);
    if (state.history.length) console.log(`  history: ${state.history.map((h) => h.to).join(' → ')}`);
    return 0;
  }

  if (cmd === 'reset') {
    const p = statePath(root);
    if (existsSync(p)) unlinkSync(p);
    console.log('✓ /next state reset');
    return 0;
  }

  if (cmd === 'require') {
    const target = pos[1];
    if (!PHASES.includes(target)) { console.error(`usage: require <${PHASES.join('|')}>`); return 2; }
    const state = loadState(root);
    const curIdx = state.phase === null ? -1 : PHASES.indexOf(state.phase);
    if (curIdx >= PHASES.indexOf(target)) {
      console.log(`✓ /next: at or past phase '${target}' (current: ${state.phase})`);
      return 0;
    }
    console.error(`✗ /next: phase '${target}' not reached (current: ${state.phase ?? '(start)'}) — blocked`);
    return 1;
  }

  if (cmd === 'approve') {
    const state = loadState(root);
    if (state.phase !== 'approval') {
      console.error(`✗ /next: approve is only valid in the 'approval' phase (current: ${state.phase ?? '(start)'})`);
      return 1;
    }
    const by = typeof flags.by === 'string' ? flags.by : null;
    if (!by) { console.error('✗ /next: approve requires --by <who>'); return 2; }
    state.approval = { by, at: new Date().toISOString(), note: typeof flags.note === 'string' ? flags.note : '' };
    saveState(root, state);
    await logTransition(root, { type: 'next-approve', by });
    console.log(`✓ /next: approval recorded by ${by}`);
    return 0;
  }

  if (cmd === 'advance') {
    const target = pos[1];
    const { loadConfig } = await import('./lib/config.mjs');
    const cfg = loadConfig(root);
    const state = loadState(root);
    const artifacts = resolveArtifacts(root, state, cfg, {
      plan: flags.plan !== undefined ? String(flags.plan) : undefined,
      report: flags.report !== undefined ? String(flags.report) : undefined,
    });

    const decision = canAdvance(state, target, artifacts);
    if (!decision.ok) {
      console.error(`✗ /next: ${decision.reason}`);
      return 1;
    }

    // The expensive/irreversible step (spawning executor subagents in worktrees) opts into the
    // guard-session budget. Passes through today (not in config.guard.scaffolderCommands); becomes
    // a real requireGuard consumer once `next:execute` is added there (roadmap Debt #4).
    if (target === 'execute') {
      const { requireGuard } = await import('./lib/guard-session.mjs');
      const g = requireGuard(root, cfg, 'next:execute');
      if (!g.ok) { console.error(`✗ /next: ${g.reason}`); return 1; }
    }

    const record = { from: decision.from, to: target, at: new Date().toISOString() };
    const nextState = {
      ...state,
      phase: target,
      history: [...state.history, record],
      artifacts: { ...state.artifacts, ...artifacts },
    };
    saveState(root, nextState);
    await logTransition(root, { type: 'next-phase', from: decision.from ?? 'start', to: target });
    console.log(`✓ /next: advanced ${decision.from ?? '(start)'} → ${target}`);
    return 0;
  }

  console.error(`usage: next-phase-gate.mjs <status|advance <phase>|require <phase>|approve --by <who>|reset>`);
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => process.exit(code));
}
