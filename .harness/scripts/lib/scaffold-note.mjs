#!/usr/bin/env node
/**
 * @description Pure core for the scaffolder commands (`incident:new` / `audit:finding`). Genericizes
 * changemappers' `create-incident-report.js` / `create-audit-finding.js` onto config-driven paths and
 * the learning-loop schema (`config.docs.learningLoop`), so a freshly scaffolded note has the EXACT
 * shape `verify-learning-loop.mjs`'s `validateNote` expects. No process/exit/fs — directly unit-testable
 * and verified against the real gate (round-trip) in `test/scaffold-note.test.mjs`.
 */

/** The command-name → note-kind wiring the guard consumes. `config.guard.scaffolderCommands` must be a
 *  subset of these keys, or the command has no consumer (doctor WARNs on that drift). */
export const SCAFFOLD_COMMANDS = { 'incident:new': 'incident', 'audit:finding': 'audit' };

/** kind → the note's learning-loop `Type` (allowedTypes is `incident`|`reference`; an audit finding is
 *  a reference-type note). */
const KIND_TYPE = { incident: 'incident', audit: 'reference' };

/** Title → kebab filename stem (path-safe, bounded length). */
export function slugify(title) {
  return (
    String(title)
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'note'
  );
}

/** `YYYY-MM-DD-<slug>.md`. Date derives from injected `now` so tests are deterministic. */
export function noteFilename(kind, title, now = Date.now()) {
  const date = new Date(now).toISOString().slice(0, 10);
  return `${date}-${slugify(title)}.md`;
}

/** kind → repo-relative target dir (from `config.docs.learningLoop`). */
export function targetDir(kind, cfg) {
  const ll = cfg?.docs?.learningLoop || {};
  return kind === 'incident' ? ll.errorsDir || 'docs/errors' : ll.auditsDir || 'docs/audits';
}

/**
 * Render a learning-loop-compliant note template. Every `requiredMetadata` key and `requiredSection`
 * from config is present, seeded with valid concrete defaults — EXCEPT the two link fields, which are
 * seeded with a `TODO:` marker on purpose: `verify-learning-loop.mjs` hard-fails a note whose
 * Guardrail/Automation Links are `TODO`/`TBD`/`none` or lack a concrete path. So the note passes the gate
 * exactly when the author replaces those links with a real `path:line` — forcing the loop to close on a
 * concrete artifact, never prose.
 */
export function renderNote(kind, title, cfg, now = Date.now()) {
  const ll = cfg?.docs?.learningLoop || {};
  const date = new Date(now).toISOString().slice(0, 10);
  const seeds = {
    Date: date,
    Type: KIND_TYPE[kind] || 'reference',
    Status: (ll.allowedStatuses && ll.allowedStatuses[0]) || 'active',
    Area: 'unspecified',
    Trigger: `manual scaffold (kaizen ${kind})`,
    'Guardrail Links': 'TODO: cite a concrete guardrail path (e.g. .harness/scripts/foo.mjs:42)',
    'Automation Links': 'TODO: cite a concrete script/hook/command path (e.g. .harness/hooks/pre-commit:1)',
  };
  const metaKeys = ll.requiredMetadata || Object.keys(seeds);
  const metaLines = metaKeys.map((k) => `**${k}:** ${seeds[k] ?? 'unspecified'}`);
  const sections = (ll.requiredSections || []).map((s) => `${s}\n\n_Fill this in._`);
  return [`# ${title}`, '', metaLines.join('\n'), '', sections.join('\n\n'), ''].join('\n');
}
