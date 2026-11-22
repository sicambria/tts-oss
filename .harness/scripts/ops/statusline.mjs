#!/usr/bin/env node
/**
 * @description Cheap token/cost status-line telemetry (P2-18, src: changemappers). Claude Code invokes
 * `.claude/settings.json`'s `statusLine.command` once per render, piping a JSON session snapshot on
 * stdin (schema confirmed 2026-07 against https://code.claude.com/docs/en/statusline). This script
 * prints ONE line: model, cost, and context-window token usage — the "cheap" telemetry the roadmap asks
 * for. No git spawn, no network — stays cheap since it re-renders on every prompt.
 *
 * Fields consumed (all optional/defensive — a missing field degrades gracefully, never throws):
 *   model.display_name, cost.total_cost_usd,
 *   context_window.total_input_tokens / total_output_tokens / used_percentage,
 *   workspace.current_dir (best-effort local event-count enrichment only — no subprocess).
 *
 * Pure core (`renderStatusline`) + a thin CLI that reads stdin.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readEvents } from './events.mjs';

function fmtTokens(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '?';
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '$?';
  return `$${n.toFixed(4)}`;
}

/**
 * Render a single status line (no embedded newline) from Claude Code's statusLine stdin JSON.
 * `eventCount`, if provided, is appended as best-effort local observability enrichment.
 * @param {object} input parsed stdin JSON (may be partial/malformed — every access is defensive)
 * @param {{eventCount?: number}} [opts]
 * @returns {string}
 */
export function renderStatusline(input, opts = {}) {
  const data = input && typeof input === 'object' ? input : {};
  const model = (data.model && data.model.display_name) || 'model';
  const cost = data.cost && typeof data.cost.total_cost_usd === 'number' ? data.cost.total_cost_usd : null;
  const cw = data.context_window || {};
  const inTok = typeof cw.total_input_tokens === 'number' ? cw.total_input_tokens : null;
  const outTok = typeof cw.total_output_tokens === 'number' ? cw.total_output_tokens : null;
  const pct = typeof cw.used_percentage === 'number' ? cw.used_percentage : null;

  const parts = [`[${model}]`];
  parts.push(fmtCost(cost));
  if (inTok !== null || outTok !== null) {
    const tokStr = `${fmtTokens(inTok ?? 0)}+${fmtTokens(outTok ?? 0)} tok`;
    parts.push(pct !== null ? `${tokStr} (${pct}%)` : tokStr);
  }
  if (typeof opts.eventCount === 'number') {
    parts.push(`${opts.eventCount} event${opts.eventCount === 1 ? '' : 's'}`);
  }
  return parts.join(' · ');
}

/** Best-effort: count events under `.harness/state/events.jsonl` relative to a workspace dir. Never
 *  throws, never spawns a subprocess (stays cheap — this is read-only fs access, not git). */
function localEventCount(cwd) {
  try {
    if (!cwd || typeof cwd !== 'string') return undefined;
    // Walk up from cwd looking for a .harness/state/events.jsonl (handles worktrees/subdirs) —
    // bounded to a handful of levels so a bad cwd can't spin.
    let dir = cwd;
    for (let i = 0; i < 6; i++) {
      const candidate = path.join(dir, '.harness', 'state', 'events.jsonl');
      if (existsSync(candidate)) {
        return readEvents(dir).length;
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

/** Synchronous stdin read (fd 0). Returns '' if stdin is closed/empty/unreadable. */
function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

/** CLI: read stdin JSON, print one status line. */
export function main() {
  const raw = readStdin();
  let data = {};
  try {
    data = raw.trim() ? JSON.parse(raw) : {};
  } catch {
    data = {};
  }
  const cwd = (data.workspace && data.workspace.current_dir) || data.cwd;
  const eventCount = localEventCount(cwd);
  console.log(renderStatusline(data, { eventCount }));
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
