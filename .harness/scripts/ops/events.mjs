#!/usr/bin/env node
/**
 * @description The observability spine's event log (P1-9, src: changemappers + Spec Kitty).
 * Append-only JSONL of harness events (decisions, retros, and future callers) written to
 * `.harness/state/events.jsonl` — runtime data, already gitignored (`.gitignore:3`), NOT committed.
 * This mirrors the runtime/committed split the harness already draws for guard-session tokens and
 * prepush logs: `events.jsonl` is derived/regenerable, while `/decide` and `/retro` write their
 * human-facing records to the committed `.harness/archive/{decisions,retros}/` dirs.
 *
 * Pure core (`logEvent`/`readEvents`/`summarize`) + a thin CLI so `/decide`, `/retro`, and any future
 * caller have something to shell out to:
 *   node events.mjs --type <type> [--key value ...]
 *
 * Never throws on a malformed line or a missing file — observability must never block the critical
 * path (precedent: `lib/log.mjs:29`).
 */
import { appendFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

const EVENTS_REL = path.join('.harness', 'state', 'events.jsonl');

/** Absolute path to the events.jsonl for a given repo root. */
export function eventsPath(root) {
  return path.join(root, EVENTS_REL);
}

/**
 * Append one event to `.harness/state/events.jsonl`. Adds `ts` (ISO) if the caller didn't supply one.
 * Creates the state dir if missing. Best-effort: returns the written record, or null on any I/O
 * failure (never throws — observability must never block the critical path).
 * @param {string} root repo root (absolute)
 * @param {{type: string, [k: string]: unknown}} fields
 */
export function logEvent(root, fields) {
  if (!fields || typeof fields.type !== 'string' || !fields.type) {
    throw new TypeError('logEvent: fields.type is required');
  }
  const record = { ts: new Date().toISOString(), ...fields };
  try {
    const dir = path.join(root, '.harness', 'state');
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    appendFileSync(eventsPath(root), JSON.stringify(record) + '\n');
    return record;
  } catch {
    return null;
  }
}

/**
 * Read + parse every event from `.harness/state/events.jsonl`. Skips (does not throw on) malformed
 * lines. Returns `[]` if the file doesn't exist yet.
 * @param {string} root repo root (absolute)
 * @returns {Array<Record<string, unknown>>}
 */
export function readEvents(root) {
  const p = eventsPath(root);
  if (!existsSync(p)) return [];
  let raw;
  try {
    raw = readFileSync(p, 'utf8');
  } catch {
    return [];
  }
  const out = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      out.push(JSON.parse(trimmed));
    } catch {
      /* skip bad line — never throw */
    }
  }
  return out;
}

/**
 * Summarize a list of events: total count, counts by `type`, and the timestamp span.
 * @param {Array<Record<string, unknown>>} events
 */
export function summarize(events) {
  const list = Array.isArray(events) ? events : [];
  const byType = {};
  for (const e of list) {
    const t = (e && typeof e.type === 'string' && e.type) || 'unknown';
    byType[t] = (byType[t] || 0) + 1;
  }
  const timestamps = list.map((e) => e && e.ts).filter(Boolean).sort();
  return {
    total: list.length,
    byType,
    firstTs: timestamps[0] || null,
    lastTs: timestamps[timestamps.length - 1] || null,
  };
}

/**
 * CLI: `node events.mjs --type <type> [--key value ...]` appends an event.
 * `node events.mjs --summarize` prints `summarize(readEvents(root))` as JSON (used by `/retro` to
 * synthesize without re-parsing the JSONL by hand) and `--events` additionally includes the raw list.
 * Any repeated `--key` overwrites earlier.
 */
export function main(argv) {
  const args = argv.slice();
  if (args.includes('--summarize')) {
    const root = gitRoot();
    const events = readEvents(root);
    const out = args.includes('--events') ? { ...summarize(events), events } : summarize(events);
    console.log(JSON.stringify(out, null, 2));
    return 0;
  }
  const fields = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const val = args[i + 1] !== undefined && !args[i + 1].startsWith('--') ? args[++i] : 'true';
      fields[key] = val;
    }
  }
  if (!fields.type) {
    console.error('✗ events: --type is required');
    return 1;
  }
  const root = gitRoot();
  const record = logEvent(root, fields);
  if (!record) {
    console.error('✗ events: failed to write event (non-fatal — observability never blocks)');
    return 1;
  }
  console.log(`✓ events: logged ${record.type} @ ${record.ts}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
