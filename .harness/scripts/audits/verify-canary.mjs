#!/usr/bin/env node
/**
 * @description L4 — contract-read canary drift gate. The behavioral half (an agent surfacing the
 * canary words at session start to prove it ingested the contract) is the read-compliance signal for
 * providers WITHOUT hooks — kaizen cannot mechanically force it (that ceiling is by design). What IS
 * mechanical, and what this gate enforces, is the *integrity* of the canary: each contract file carries
 * exactly one `<!-- CANARY: WORD -->` marker, and AGENTS.md's protocol section lists every marker file.
 * A marker added/removed without updating the protocol (or a duplicate) HARD-FAILS — so the canary can
 * never silently rot into a signal nobody can satisfy.
 *
 * Pure core (`checkCanary`) + a CLI that reads the real tree. No secrets: the marker words are inert.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

/** The contract files that MUST each carry one canary marker. constitution.md is intentionally absent
 *  (it is declared immutable — tagging it would be self-contradicting). */
export const CANARY_FILES = [
  'AGENTS.md',
  '.harness/memory/rules.md',
  '.harness/INVARIANTS.md',
  '.harness/memory/memory.md',
];

/** The AGENTS.md heading that opens the protocol section listing the marker files. */
export const PROTOCOL_HEADING = '## Session-start contract-read canary';

const MARKER_RE = /<!--\s*CANARY:\s*([A-Za-z0-9]+)\s*-->/g;

/** Extract the protocol section body (heading → next `## ` or EOF). '' if the heading is absent. */
function protocolSection(agentsContent) {
  const i = agentsContent.indexOf(PROTOCOL_HEADING);
  if (i === -1) return '';
  const after = agentsContent.slice(i + PROTOCOL_HEADING.length);
  const next = after.indexOf('\n## ');
  return next === -1 ? after : after.slice(0, next);
}

/**
 * Verify canary integrity. Pure: takes a `{ relPath: content }` map so tests can drive it directly.
 * @param {Record<string,string>} files
 * @returns {{ ok: boolean, errors: string[], words: Record<string,string> }}
 */
export function checkCanary(files) {
  const errors = [];
  const words = {};
  for (const f of CANARY_FILES) {
    const content = files[f];
    if (content == null) {
      errors.push(`missing contract file: ${f}`);
      continue;
    }
    const found = [...content.matchAll(MARKER_RE)].map((m) => m[1]);
    if (found.length === 0) errors.push(`no CANARY marker in ${f} (expected exactly one)`);
    else if (found.length > 1) errors.push(`${found.length} CANARY markers in ${f} (expected exactly one)`);
    else words[f] = found[0];
  }
  // The AGENTS.md protocol section must NAME every other marker file — the drift check: you cannot
  // add/remove a marker host without also updating the instruction that tells agents where to look.
  const section = protocolSection(files['AGENTS.md'] || '');
  if (!section) {
    errors.push(`AGENTS.md is missing the "${PROTOCOL_HEADING}" protocol section`);
  } else {
    for (const f of CANARY_FILES) {
      if (f === 'AGENTS.md') continue;
      if (!section.includes(f)) errors.push(`AGENTS.md protocol section does not list marker file: ${f}`);
    }
  }
  return { ok: errors.length === 0, errors, words };
}

/** Read the canary files from a repo root into a `{ relPath: content }` map (missing → absent key). */
export function readCanaryFiles(root) {
  const files = {};
  for (const f of CANARY_FILES) {
    try {
      files[f] = readFileSync(path.join(root, f), 'utf8');
    } catch {
      /* leave absent → checkCanary reports it */
    }
  }
  return files;
}

export function main() {
  const root = gitRoot();
  const res = checkCanary(readCanaryFiles(root));
  if (res.ok) {
    console.log(`✓ canary: ${CANARY_FILES.length} contract markers intact + listed in AGENTS.md protocol`);
    return 0;
  }
  console.error('✗ canary: contract-read canary integrity FAILED');
  for (const e of res.errors) console.error(`  - ${e}`);
  return 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
