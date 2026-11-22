#!/usr/bin/env node
/**
 * @description Identity-scan gate — blocks host-unique / personal identifiers from being committed or
 * pushed. Companion to the secret-scan gate: same fail-closed, baseline+expiry-allowlist governance,
 * but the target is host FINGERPRINTS (absolute /home/<user>/ paths, the running host's username /
 * hostname) rather than credentials. Detection rules and their write-time inverse live in
 * ../lib/identity.mjs so the memory-capture writer can never emit what this gate then rejects.
 *
 * The structural /home/<user>/ rule is the portable guarantee (fires in CI too); the runtime
 * username/hostname layer is a machine-local bonus (see lib/identity.mjs). PUBLISHED authorship — a
 * project's own GitHub handle in repo URLs / LICENSE — is intentional and never matches (it differs
 * from the OS user); genuine residue is suppressed via the shared baseline / allowlist.
 *
 * Modes:
 *   --staged        scan added (+) lines of the staged diff (pre-commit gate).
 *   <file> [file…]  scan the named files.
 *   (no args)       detect mode — scan every git-tracked text file.
 *
 * Config seams (ENV-first via seam(), safe inline defaults — no config.json edit required):
 *   security.identity.enabled   (env KAIZEN_IDENTITY_ENABLED)  default true — 'false'/'0' disables.
 *   security.allowlistPath / security.baselinePath — shared with the secret gate (rule-namespaced
 *   fingerprints can't collide).
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig, seam } from '../lib/config.mjs';
import { repoRoot as gitRoot, git } from '../lib/repo.mjs';
import { scanLine, scanText, fingerprint, hostFingerprints } from '../lib/identity.mjs';
import { loadBaseline, parseAllowlist, evalAllowlist } from './verify-secrets.mjs';

/** Redact a detected identifier for safe log output (paths/usernames aren't secrets, but keep it terse). */
export function redact(v) {
  return v.length <= 8 ? v : `${v.slice(0, 5)}…${v.slice(-2)}`;
}

/** Parse added (+) lines of the staged diff → [{ file, line, text }]. */
function stagedAddedLines(root) {
  const r = git(['diff', '--cached', '--unified=0', '--no-color', '--diff-filter=ACMR'], { cwd: root });
  if (r.code !== 0) return [];
  const out = [];
  let file = null;
  let lineNo = 0;
  for (const raw of r.out.split('\n')) {
    if (raw.startsWith('+++ ')) {
      const p = raw.slice(4).trim();
      file = p === '/dev/null' ? null : p.replace(/^b\//, '');
    } else if (raw.startsWith('@@')) {
      const mm = /\+(\d+)/.exec(raw);
      lineNo = mm ? parseInt(mm[1], 10) : 0;
    } else if (raw.startsWith('+')) {
      out.push({ file, line: lineNo, text: raw.slice(1) });
      lineNo++;
    }
  }
  return out;
}

/** Detect mode: scan every git-tracked text file (skips binary and >1 MiB blobs). */
function scanTrackedFiles(root, fp) {
  const r = git(['ls-files'], { cwd: root });
  if (r.code !== 0) return [];
  const findings = [];
  for (const rel of r.out.split('\n').filter(Boolean)) {
    let content;
    try {
      const buf = readFileSync(path.join(root, rel));
      if (buf.length > 1024 * 1024 || buf.includes(0)) continue;
      content = buf.toString('utf8');
    } catch { continue; }
    findings.push(...scanText(content, rel, fp));
  }
  return findings;
}

export function main(argv, opts = {}) {
  const now = opts.now ?? Date.now();
  const root = opts.root ?? gitRoot();
  const cfg = loadConfig(root);

  const enabled = seam('KAIZEN_IDENTITY_ENABLED', cfg.security?.identity?.enabled, true);
  if (enabled === false || enabled === 'false' || enabled === '0') {
    console.error('✓ identity-scan: disabled via security.identity.enabled');
    return 0;
  }

  // Fingerprints are injectable for tests; otherwise derived (safely) from the running host.
  const fp = opts.fingerprints ?? hostFingerprints();
  const staged = argv.includes('--staged');

  const allowlistPath = seam('KAIZEN_ALLOWLIST_PATH', cfg.security?.allowlistPath, '.harness/security/allowlist.yaml');
  const baselinePath = seam('KAIZEN_BASELINE_PATH', cfg.security?.baselinePath, '.harness/security/.secrets.baseline');

  const baseline = loadBaseline(root, baselinePath);
  if (baseline.error) { console.error(`✗ identity-scan: ${baseline.error} (fail closed)`); return 1; }

  const alFile = path.isAbsolute(allowlistPath) ? allowlistPath : path.join(root, allowlistPath);
  let alEntries = [];
  if (existsSync(alFile)) {
    try { alEntries = parseAllowlist(readFileSync(alFile, 'utf8')); }
    catch (e) { console.error(`✗ identity-scan: malformed allowlist ${allowlistPath}: ${e.message} (fail closed)`); return 1; }
  }
  const al = evalAllowlist(alEntries, now);

  let failed = false;
  if (al.malformed.length) {
    console.error(`✗ identity-scan: ${al.malformed.length} allowlist entr${al.malformed.length === 1 ? 'y' : 'ies'} missing fingerprint/expires — fail closed.`);
    failed = true;
  }
  for (const e of al.expired) {
    console.error(`✗ identity-scan: allowlist entry EXPIRED ${e.expires} (fingerprint ${String(e.fingerprint).slice(0, 12)}…) — re-sanitize and remove the entry.`);
    failed = true;
  }

  // Gather findings for the requested mode.
  const fileArgs = argv.filter((a) => !a.startsWith('--'));
  let findings = [];
  if (fileArgs.length) {
    for (const f of fileArgs) {
      const abs = path.isAbsolute(f) ? f : path.join(root, f);
      if (!existsSync(abs)) { console.error(`✗ identity-scan: no such file ${f}`); return 1; }
      findings.push(...scanText(readFileSync(abs, 'utf8'), f, fp));
    }
  } else if (staged) {
    for (const { file, line, text } of stagedAddedLines(root)) {
      for (const h of scanLine(text, fp)) {
        findings.push({ file, line, rule: h.rule, value: h.value, fingerprint: fingerprint(h.rule, h.value) });
      }
    }
  } else {
    findings = scanTrackedFiles(root, fp);
  }

  const active = findings.filter((f) => !baseline.fingerprints.has(f.fingerprint) && !al.active.has(f.fingerprint));
  if (active.length) {
    console.error(`✗ identity-scan: ${active.length} host/personal identifier(s) found:`);
    for (const f of active) console.error(`  ${f.file}:${f.line} [${f.rule}] ${redact(f.value)}  fingerprint=${f.fingerprint}`);
    console.error('  → replace host paths with ~ or <user>/<host> placeholders; for legitimate residue,');
    console.error('    baseline the fingerprint in .harness/security/.secrets.baseline or add a temporary allowlist.yaml entry.');
    failed = true;
  }

  if (failed) return 1;
  console.error('✓ identity-scan: clean');
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
