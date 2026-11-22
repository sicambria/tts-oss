#!/usr/bin/env node
/**
 * @description Advisory resource-budget observations (pure aggregation, no enforcement).
 * Aggregates explicitly supplied events only — there is no hidden global tracker, no
 * estimator, and no hard cap. Each event's provenance is `reported`, `observed`, or
 * `unknown`; unknown-provenance events stay visible in the report but are excluded
 * from totals and from threshold decisions. Threshold warnings are advisory strings,
 * never blocks. Runtime observations belong in gitignored state, not committed records.
 *
 * Pure module: `aggregateBudget` / `thresholdWarnings` / `renderBudget`. No CLI side
 * effects beyond an optional `--stdin` JSON helper for manual samples.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const PROVENANCE = ['reported', 'observed', 'unknown'];

/** Event fields that must never be stored — prompts/credentials have no place in observations. */
const SECRETISH = /(prompt|secret|token|api[-_]?key|password|credential|private[-_]?key)/i;

/** Legitimate metric keys — always kept (so the scrub can never eat `tokens`). */
const METRIC_KEYS = new Set(['phase', 'tokens', 'ms', 'tools', 'provenance']);

/**
 * Drop secret-bearing fields from one event; returns {event, scrubbed:string[]}.
 * A scrub is reported, never silent.
 */
export function scrubEvent(event) {
  const clean = {};
  const scrubbed = [];
  for (const [k, v] of Object.entries(event || {})) {
    if (METRIC_KEYS.has(k)) clean[k] = v;
    else if (SECRETISH.test(k)) scrubbed.push(k);
    else clean[k] = v;
  }
  return { event: clean, scrubbed };
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

/**
 * Pure aggregation over supplied events.
 * Event: {phase?:string, tokens?:number, ms?:number, tools?:number, provenance?:string}
 * @returns {{phases:object, totals:object, provenance:object, unknownEvents:Array, warnings:Array}}
 */
export function aggregateBudget(events) {
  const list = Array.isArray(events) ? events : [];
  const phases = {};
  const totals = { tokens: 0, ms: 0, tools: 0, events: 0 };
  const provenance = { reported: 0, observed: 0, unknown: 0 };
  const unknownEvents = [];
  const warnings = [];

  list.forEach((raw, idx) => {
    const { event, scrubbed } = scrubEvent(raw);
    if (scrubbed.length) {
      warnings.push(`event ${idx}: scrubbed secret-bearing field(s) ${scrubbed.join(', ')} — never log prompts/credentials`);
    }
    let prov = String(event.provenance || 'unknown').toLowerCase();
    if (!PROVENANCE.includes(prov)) {
      warnings.push(`event ${idx}: unknown provenance "${event.provenance}" treated as "unknown"`);
      prov = 'unknown';
    }
    provenance[prov] += 1;
    const entry = {
      idx,
      phase: String(event.phase || 'unphased'),
      tokens: num(event.tokens),
      ms: num(event.ms),
      tools: num(event.tools),
      provenance: prov,
    };
    if (prov === 'unknown') {
      // Visible but excluded from every total and decision.
      unknownEvents.push(entry);
      return;
    }
    totals.tokens += entry.tokens;
    totals.ms += entry.ms;
    totals.tools += entry.tools;
    totals.events += 1;
    const ph = (phases[entry.phase] = phases[entry.phase] || { tokens: 0, ms: 0, tools: 0, events: 0 });
    ph.tokens += entry.tokens;
    ph.ms += entry.ms;
    ph.tools += entry.tools;
    ph.events += 1;
  });

  return { phases, totals, provenance, unknownEvents, warnings };
}

/**
 * Advisory threshold warnings over a report. Unknown-provenance events are never
 * consulted (they were excluded at aggregation). Returns strings only — never blocks.
 */
export function thresholdWarnings(report, thresholds = {}) {
  const out = [];
  const t = report && report.totals ? report.totals : { tokens: 0, ms: 0, tools: 0 };
  for (const key of ['tokens', 'ms', 'tools']) {
    const limit = Number(thresholds[key]);
    if (Number.isFinite(limit) && limit >= 0 && t[key] > limit) {
      out.push(`advisory: ${key} total ${t[key]} exceeds observation threshold ${limit} (reported+observed only)`);
    }
  }
  return out;
}

/** Human-readable rendering of a report (totals + provenance + unknown-visible). */
export function renderBudget(report, thresholds = {}) {
  const lines = [];
  lines.push('budget observations (advisory — no caps, no enforcement)');
  const t = report.totals;
  lines.push(`totals (reported+observed): tokens=${t.tokens} ms=${t.ms} tools=${t.tools} events=${t.events}`);
  lines.push(`provenance: reported=${report.provenance.reported} observed=${report.provenance.observed} unknown=${report.provenance.unknown} (excluded from totals)`);
  for (const [phase, p] of Object.entries(report.phases)) {
    lines.push(`  phase ${phase}: tokens=${p.tokens} ms=${p.ms} tools=${p.tools} events=${p.events}`);
  }
  if (report.unknownEvents.length) {
    lines.push(`unknown-provenance events (visible, excluded): ${report.unknownEvents.length}`);
    for (const u of report.unknownEvents) {
      lines.push(`  [${u.idx}] phase=${u.phase} tokens=${u.tokens} ms=${u.ms} tools=${u.tools}`);
    }
  }
  for (const w of [...report.warnings, ...thresholdWarnings(report, thresholds)]) lines.push(`! ${w}`);
  return lines.join('\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  // Manual-sample helper only: pipe a JSON event array via stdin.
  let body = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (c) => { body += c; });
  process.stdin.on('end', () => {
    try {
      console.log(renderBudget(aggregateBudget(JSON.parse(body || '[]'))));
    } catch (e) {
      console.error(`✗ budget-observations: invalid JSON input — ${e.message}`);
      process.exit(1);
    }
  });
}
