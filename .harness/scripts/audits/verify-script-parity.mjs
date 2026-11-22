#!/usr/bin/env node
/**
 * @description Dual-tree parity gate (Fellow review C4). The harness dogfoods its OWN enforcement:
 * the live `.harness/` tree is the running copy, and `templates/core/.harness/` is the identical copy
 * shipped to adopters by `kaizen init`. If the two silently diverge, a fix (or a break) lands in one
 * tree and adopters get the stale/broken other — with a green suite, because nothing compared them.
 * `.harness/scripts/pre-commit.mjs` referenced this gate before it existed; this makes that true.
 *
 * The gate asserts byte-identity over an EXPLICIT manifest of TRUE mirrors, computed as the union of
 * files matching `MIRROR_INCLUDE` in EITHER tree (so a file present in one tree but missing from the
 * other is caught in both directions), minus `REPO_LOCAL_EXCLUDE`. Scoping is the whole correctness of
 * the gate: repo-local / init-emitted-then-diverge files (config.json, runtime state, the live hot
 * memory index, the accumulating secret baseline, dated archive entries, active plans, opt-in profiles)
 * are NOT byte-mirrors and are excluded by name — including them would false-fail every commit.
 *
 * Pure core (`computeManifest` / `checkParity`) + a thin fail-closed CLI, mirroring the shape of the
 * sibling audits (verify-secrets.mjs, verify-test-gaming.mjs).
 */
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

/**
 * TRUE dual-tree mirrors — every file the shipped enforcement tree must carry byte-identical to the
 * live one. Patterns are matched against a POSIX rel-path under a harness root (`.harness` /
 * `templates/core/.harness`). The scripts pattern covers every `.mjs` under `scripts/` —
 * audits/, gates/, lib/, ops/ and top-level.
 */
export const MIRROR_INCLUDE = [
  /^scripts\/.+\.mjs$/,
  /^gates\/[^/]+\.json$/,
  /^hooks\/[^/]+$/,
  /^ci\/[^/]+\.yml$/,
  /^subagents\/[^/]+\.md$/,
  /^reference\/[^/]+\.md$/,
  /^adapters\/[^/]+\.template\.md$/,
  /^memory\/(project|user|rules|conventions|glossary)\.md$/,
  /^memory\/source-aware\.json$/,
  /^security\/(allowlist\.yaml|README\.md)$/,
  /^INVARIANTS\.md$/,
  /^constitution\.md$/,
];

/** Native repository-root mirrors shipped beside templates/core/.harness/. */
export const NATIVE_MIRROR_INCLUDE = [
  /^\.claude\/settings\.json$/,
  /^\.claude\/skills\/[^/]+\/SKILL\.md$/,
  /^\.claude\/commands\/[^/]+\.md$/,
];

/**
 * Repo-local-only OR init-emitted-then-diverge paths — intentionally NOT byte-mirrors. Explicit by
 * design (the orchestrator + AGENTS.md both require the excluded set be named, not implied). Kept as a
 * second, independent subtraction so a future broadening of MIRROR_INCLUDE can never silently pull one
 * of these into the byte comparison. `memory/memory.md` (live hot index vs the "(nothing yet)" seed)
 * and `security/.secrets.baseline` (accumulated repo fingerprint vs `{secrets:{}}` seed) are the two
 * shared files that genuinely differ between the trees — verified by a full-intersection diff.
 */
export const REPO_LOCAL_EXCLUDE = [
  /^config\.json$/,                  // per-repo config (secretScanner, verify contract, …)
  /^state\//,                        // gitignored runtime state (events.jsonl, snapshots)
  /^memory\/memory\.md$/,            // live hot index — filled post-install; seed says "(nothing yet)"
  /^memory\/episodic\//,             // dated session journals (repo-specific)
  /^memory\/procedural\//,           // distilled reusable skills (repo-specific)
  /^security\/\.secrets\.baseline$/, // accumulates repo fingerprints; seed is {secrets:{}}
  /^archive\//,                      // dated decisions/retros + postmortems index (repo-specific)
  /^plans\//,                        // active plan files (repo-specific; only .gitkeep is shipped)
  /^profiles\//,                     // opt-in profile fragments (not the core mirror)
  /^specs\//,                        // repo-specific specs (only .gitkeep is shipped)
  /(?:^|\/)\.gitkeep$/,              // structural placeholders, not enforcement content
];

/** True iff a POSIX rel-path is a byte-mirror we must compare across the two trees. */
export function isMirror(rel) {
  return MIRROR_INCLUDE.some((re) => re.test(rel)) && !REPO_LOCAL_EXCLUDE.some((re) => re.test(rel));
}

/** True iff a repository-root native path is a shipped byte-mirror. */
export function isNativeMirror(rel) {
  return NATIVE_MIRROR_INCLUDE.some((re) => re.test(rel));
}

/** Recursively list POSIX rel-paths of every file under `root` (missing root → []). */
function walkFiles(root) {
  const out = [];
  if (!existsSync(root)) return out;
  const stack = [''];
  while (stack.length) {
    const relDir = stack.pop();
    const absDir = relDir ? path.join(root, relDir) : root;
    for (const ent of readdirSync(absDir, { withFileTypes: true })) {
      const rel = relDir ? `${relDir}/${ent.name}` : ent.name;
      if (ent.isDirectory()) stack.push(rel);
      else if (ent.isFile()) out.push(rel);
    }
  }
  return out;
}

/**
 * The canonical mirror manifest = union of mirror-matching files across BOTH trees, sorted. Union
 * (not just one tree) is deliberate: a mirror-category file added to only one tree is itself drift.
 */
export function computeManifest(liveRoot, shipRoot) {
  return computeManifestFor(liveRoot, shipRoot, isMirror);
}

function computeManifestFor(liveRoot, shipRoot, matcher) {
  const set = new Set();
  for (const rel of walkFiles(liveRoot)) if (matcher(rel)) set.add(rel);
  for (const rel of walkFiles(shipRoot)) if (matcher(rel)) set.add(rel);
  return [...set].sort();
}

/**
 * Byte-compare every manifest entry across the two trees.
 * @returns {{manifest:string[], findings:{rel:string, kind:'byte-diff'|'missing-live'|'missing-ship'}[]}}
 */
export function checkParity(liveRoot, shipRoot) {
  return checkParityFor(liveRoot, shipRoot, isMirror);
}

function checkParityFor(liveRoot, shipRoot, matcher) {
  const manifest = computeManifestFor(liveRoot, shipRoot, matcher);
  const findings = [];
  for (const rel of manifest) {
    const lp = path.join(liveRoot, rel);
    const sp = path.join(shipRoot, rel);
    if (!existsSync(lp)) { findings.push({ rel, kind: 'missing-live' }); continue; }
    if (!existsSync(sp)) { findings.push({ rel, kind: 'missing-ship' }); continue; }
    if (!readFileSync(lp).equals(readFileSync(sp))) findings.push({ rel, kind: 'byte-diff' });
  }
  return { manifest, findings };
}

/** Compare native `.claude/` payloads at the repository root. */
export function checkNativeParity(liveRoot, shipRoot) {
  return checkParityFor(liveRoot, shipRoot, isNativeMirror);
}

const KIND_MSG = {
  'byte-diff': 'differs — not byte-identical across the two trees',
  'missing-live': 'shipped in templates/core/.harness/ but MISSING from live .harness/',
  'missing-ship': 'present in live .harness/ but MISSING from shipped templates/core/.harness/',
};

/** CLI: fail-closed. Exit 1 on any divergence. `opts` overrides roots for tests. */
export function main(argv = [], opts = {}) {
  const root = opts.root ?? gitRoot();
  const liveRoot = opts.liveRoot ?? path.join(root, '.harness');
  const shipRoot = opts.shipRoot ?? path.join(root, 'templates', 'core', '.harness');

  // Dual-tree parity is a kaizen-SOURCE-repo invariant: only this repo ships BOTH the live `.harness/`
  // and the `templates/core/.harness/` copy it dogfoods. An ADOPTER install has only the live tree
  // (kaizen init materialized `.harness/` from the package, with no templates/core/ payload), so there
  // is nothing to compare — pass. Skipping here (rather than failing) is what lets the adopter's own
  // bootstrap commit run this gate without blocking. `existsSync` on a directory is the topology probe.
  if (!existsSync(shipRoot)) {
    console.error('✓ script-parity: no shipped templates/core/.harness/ tree (adopter install) — dual-tree parity is a kaizen-source-repo check; nothing to compare.');
    return 0;
  }

  const harnessResult = checkParity(liveRoot, shipRoot);
  const nativeResult = checkNativeParity(root, path.join(root, 'templates', 'core'));
  const findings = [
    ...harnessResult.findings.map((f) => ({ ...f, scope: '.harness/' })),
    ...nativeResult.findings.map((f) => ({ ...f, scope: 'native/' })),
  ];
  if (findings.length) {
    console.error(`✗ script-parity: ${findings.length} dual-tree divergence(s):`);
    for (const f of findings) console.error(`  [${f.scope}] ${f.rel}: ${KIND_MSG[f.kind]}`);
    console.error('  → mirror the change into BOTH trees byte-identically in the same commit (a shipped gate must equal the live one it dogfoods).');
    return 1;
  }
  console.error(`✓ script-parity: ${harnessResult.manifest.length + nativeResult.manifest.length} dual-tree file(s) byte-identical across live + shipped`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
