#!/usr/bin/env node
/**
 * @description The closed learning loop (genericized). Walks the errors/incidents directory,
 * enforces each note's metadata + required sections, and regenerates a DETERMINISTIC INDEX.md
 * (generated, never hand-edited — so it can't drift). `--write` regenerates the index;
 * default (check) mode exits 1 if a note is malformed or the on-disk index is stale.
 *
 * Schema is config-driven (config.docs.learningLoop): errorsDir, requiredMetadata, requiredSections,
 * allowedTypes, allowedStatuses. A concrete guardrail/automation citation (a repo path) is required
 * so the loop can only close with a real prevention artifact, never prose.
 */
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

const PATH_LIKE = /[A-Za-z0-9_./-]+\.[A-Za-z0-9]+|scripts?\/|\.harness\//;
const PLACEHOLDER = /\b(TBD|TODO|none)\b/i;

// A cited prevention path inside a Guardrail/Automation Links value. Extract path-shaped tokens
// (contain "/" or a file extension); the `:`/`#` are outside the class so a trailing ":line"/"#anchor"
// is dropped naturally. Precision over recall: a token we cannot confidently read as a repo path
// (a bare word/command, a glob, a protocol-relative URL) is left unchecked, never false-flagged.
const CITED_TOKEN = /[A-Za-z0-9_./*-]+/g; // `*` in-class so a glob is captured whole, then skipped
const CITE_SKIP = /^(N\/A|TBD|TODO|FIXME|none|-+)$/i;

export function extractCitedPaths(value) {
  if (!value) return [];
  const out = [];
  for (const tok of value.match(CITED_TOKEN) || []) {
    if (CITE_SKIP.test(tok) || tok.includes('*') || tok.startsWith('//')) continue;
    if (!(tok.includes('/') || /\.[A-Za-z0-9]+$/.test(tok))) continue; // bare word/command, not a path
    out.push(tok);
  }
  return out;
}

function walk(dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) out.push(...walk(p));
    else if (name.endsWith('.md') && name !== 'INDEX.md') out.push(p);
  }
  return out;
}

function parseMeta(content) {
  const meta = {};
  for (const line of content.split('\n')) {
    const m = line.match(/^\*\*([A-Za-z /-]+):\*\*\s*(.*)$/) || line.match(/^-\s*\*\*([A-Za-z /-]+):\*\*\s*(.*)$/);
    if (m) meta[m[1].trim()] = m[2].trim();
  }
  return meta;
}

/**
 * Validate one note; returns errors[].
 * @param {string} content
 * @param {object} ll learningLoop config
 */
export function validateNote(content, ll, label = 'note', ctx = {}) {
  const errors = [];
  const meta = parseMeta(content);
  for (const key of ll.requiredMetadata || []) {
    if (!(key in meta) || !meta[key]) errors.push(`${label}: missing metadata "${key}"`);
  }
  if (meta.Date && !/^\d{4}-\d{2}-\d{2}$/.test(meta.Date)) errors.push(`${label}: Date must be YYYY-MM-DD`);
  if (meta.Type && ll.allowedTypes && !ll.allowedTypes.includes(meta.Type)) errors.push(`${label}: Type "${meta.Type}" not in ${ll.allowedTypes.join('/')}`);
  if (meta.Status && ll.allowedStatuses && !ll.allowedStatuses.includes(meta.Status)) errors.push(`${label}: Status "${meta.Status}" not in ${ll.allowedStatuses.join('/')}`);
  for (const sec of ll.requiredSections || []) {
    if (!content.includes(sec)) errors.push(`${label}: missing required section "${sec}"`);
  }
  // The loop must close on a concrete artifact, not prose.
  const gl = meta['Guardrail Links'] || '';
  const al = meta['Automation Links'] || '';
  if (gl && (PLACEHOLDER.test(gl) || !PATH_LIKE.test(gl))) errors.push(`${label}: "Guardrail Links" must cite a concrete repo path (not TBD/none)`);
  if (meta.Type === 'incident' && al && (PLACEHOLDER.test(al) || !PATH_LIKE.test(al))) errors.push(`${label}: incident "Automation Links" must cite a concrete script/hook/command`);

  // Citation LIVENESS (changemappers eacd003cb): a cited prevention path that no longer exists on disk
  // is a silently-rotted guardrail — the note claims a prevention artifact that isn't there. The
  // PATH_LIKE checks above attack "not path-shaped"; this attacks "path-shaped but dead". Only runs when
  // a repo root (or an injected `exists` predicate) is supplied — pure schema-only unit calls omit it and
  // stay I/O-free. changemappers measured ~58/3349 cited prevention paths pointing at deleted files.
  const exists = ctx.exists || (ctx.root ? (rel) => existsSync(path.join(ctx.root, rel)) : null);
  if (exists) {
    for (const key of ['Guardrail Links', 'Automation Links']) {
      for (const p of extractCitedPaths(meta[key])) {
        if (!exists(p)) errors.push(`${label}: "${key}" cites a path that does not exist on disk: ${p} — a dead prevention link (restore the file, fix the path, or update the note)`);
      }
    }
  }
  return errors;
}

function buildIndex(notes) {
  const rows = notes
    .map((n) => {
      const meta = parseMeta(n.content);
      const title = (n.content.match(/^#\s+(.*)$/m) || [, path.basename(n.rel)])[1];
      return { rel: n.rel, date: meta.Date || '', type: meta.Type || '', status: meta.Status || '', title };
    })
    .sort((a, b) => (b.date + b.rel).localeCompare(a.date + a.rel));
  const lines = [
    '# Incident & Error Index',
    '',
    '<!-- GENERATED by verify-learning-loop.mjs — do not edit by hand. Run `kaizen` knowledge:index. -->',
    '',
    '| Date | Type | Status | Note |',
    '|------|------|--------|------|',
    ...rows.map((r) => `| ${r.date} | ${r.type} | ${r.status} | [${r.title}](${r.rel}) |`),
    '',
  ];
  return lines.join('\n');
}

/**
 * Validate + index one learning-loop directory (errors or audits). Both dirs share the same schema
 * (`validateNote`) and INDEX contract; audit findings were previously ungated because only `errorsDir`
 * was ever walked. Returns `{ ok, count }`; a dir that doesn't exist yet is a clean no-op.
 * @param {string} dir absolute path to the note directory
 * @param {object} ll learningLoop config
 * @param {string} root repo root (absolute)
 * @param {boolean} write regenerate INDEX.md when true; else assert it is current
 * @returns {{ ok: boolean, count: number }}
 */
function processDir(dir, ll, root, write) {
  if (!existsSync(dir)) return { ok: true, count: 0 }; // nothing to index yet
  const files = walk(dir);
  const notes = files.map((f) => ({ rel: path.relative(root, f).split(path.sep).join('/'), content: readFileSync(f, 'utf8') }));

  let ok = true;
  for (const n of notes) {
    const errs = validateNote(n.content, ll, n.rel, { root });
    for (const e of errs) { console.error(`✗ ${e}`); ok = false; }
  }

  const indexPath = path.join(dir, 'INDEX.md');
  const generated = buildIndex(notes);
  if (write) {
    writeFileSync(indexPath, generated);
    console.log(`✓ learning-loop: ${path.relative(root, dir)}/INDEX.md regenerated (${notes.length} notes)`);
    return { ok, count: notes.length };
  }
  // check mode: index must match (only if there are notes)
  if (notes.length > 0) {
    const onDisk = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : '';
    if (onDisk.trim() !== generated.trim()) {
      console.error(`✗ learning-loop: ${path.relative(root, dir)}/INDEX.md is stale — run knowledge:index`);
      ok = false;
    }
  }
  return { ok, count: notes.length };
}

export function main(argv) {
  const write = argv.includes('--write');
  const root = gitRoot();
  const config = loadConfig(root);
  const ll = config.docs?.learningLoop || {};
  const dirs = [
    path.join(root, ll.errorsDir || 'docs/errors'),
    path.join(root, ll.auditsDir || 'docs/audits'),
  ];

  let ok = true;
  let total = 0;
  for (const dir of dirs) {
    const res = processDir(dir, ll, root, write);
    ok = ok && res.ok;
    total += res.count;
  }

  if (ok && !write) console.log(`✓ learning-loop: ${total} note(s) valid across errors+audits, indexes current`);
  return ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
