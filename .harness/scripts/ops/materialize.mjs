#!/usr/bin/env node
/**
 * @description The observability spine's serverless dashboard (P1-9, src: changemappers + Spec Kitty).
 * Reads `.harness/state/events.jsonl` and renders a SELF-CONTAINED static `dashboard.html` — a simple
 * kanban/summary: counts by event type, recent decisions, retro links. Pure Node string templating, no
 * deps, no external assets, no build step ("serverless" = open the file in a browser). Written as
 * `.mjs` (never `.sh`) per this cluster's brief.
 *
 * Pure core (`renderDashboard`) + a thin CLI:
 *   node materialize.mjs   # reads events.jsonl, writes .harness/state/dashboard.html
 */
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { readEvents, summarize } from './events.mjs';

const DASHBOARD_REL = path.join('.harness', 'state', 'dashboard.html');

export function dashboardPath(root) {
  return path.join(root, DASHBOARD_REL);
}

/** Minimal HTML-escape — events may contain arbitrary strings (titles, summaries). */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/**
 * Render a self-contained dashboard.html from an events array. Pure — no fs access — so it's directly
 * unit-testable against a fixture events array.
 * @param {Array<Record<string, unknown>>} events
 * @returns {string} full HTML document
 */
export function renderDashboard(events) {
  const list = Array.isArray(events) ? events : [];
  const s = summarize(list);
  const typeRows = Object.entries(s.byType)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `<tr><td>${esc(type)}</td><td>${count}</td></tr>`)
    .join('\n');

  const decisions = list
    .filter((e) => e && e.type === 'decision')
    .slice(-20)
    .reverse();
  const decisionItems = decisions
    .map((d) => {
      const summary = esc(d.summary || d.title || '(no summary)');
      const file = d.file ? ` — <code>${esc(d.file)}</code>` : '';
      return `<li><time>${esc(d.ts)}</time> ${summary}${file}</li>`;
    })
    .join('\n');

  const retros = list
    .filter((e) => e && e.type === 'retro')
    .slice(-20)
    .reverse();
  const retroItems = retros
    .map((r) => {
      const file = r.file ? `<a href="${esc(r.file)}">${esc(r.file)}</a>` : esc(r.summary || '(retro)');
      return `<li><time>${esc(r.ts)}</time> ${file}</li>`;
    })
    .join('\n');

  const generatedAt = new Date().toISOString();

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>kaizen observability dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
  table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
  th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #eee; }
  ul { padding-left: 1.1rem; }
  li { margin: .3rem 0; }
  time { color: #666; font-size: .85em; margin-right: .5em; }
  code { background: #f3f3f3; padding: 0 .3em; border-radius: 3px; }
  .muted { color: #888; }
  @media (prefers-color-scheme: dark) {
    body { background: #14161a; color: #e6e6e6; }
    th, td { border-color: #333; }
    h2 { border-color: #333; }
    code { background: #23262c; }
    time { color: #999; }
  }
</style>
</head>
<body>
<h1>kaizen observability dashboard</h1>
<p class="muted">Generated ${esc(generatedAt)} from ${s.total} event(s)${s.firstTs ? ` spanning ${esc(s.firstTs)} → ${esc(s.lastTs)}` : ''}.</p>

<h2>Counts by type</h2>
<table>
<thead><tr><th>type</th><th>count</th></tr></thead>
<tbody>
${typeRows || '<tr><td colspan="2" class="muted">no events yet</td></tr>'}
</tbody>
</table>

<h2>Recent decisions</h2>
<ul>
${decisionItems || '<li class="muted">no decisions logged yet</li>'}
</ul>

<h2>Retro links</h2>
<ul>
${retroItems || '<li class="muted">no retros logged yet</li>'}
</ul>
</body>
</html>
`;
}

/** CLI: read events.jsonl, write dashboard.html. */
export function main() {
  const root = gitRoot();
  const events = readEvents(root);
  const html = renderDashboard(events);
  const dir = path.join(root, '.harness', 'state');
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  writeFileSync(dashboardPath(root), html);
  console.log(`✓ materialize: wrote ${dashboardPath(root)} from ${events.length} event(s)`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
