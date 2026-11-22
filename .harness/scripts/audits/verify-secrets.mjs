#!/usr/bin/env node
/**
 * @description Secret-scan gate — portable secret-governance kit (ROADMAP P1-8 + Current-Debt #3).
 * Two enforcement tiers, selected by `security.secretScanner`:
 *   - 'gitleaks' + gitleaks present → run gitleaks; non-zero = BLOCK.
 *   - 'gitleaks' + gitleaks ABSENT → FAIL CLOSED (enforcement expected but unavailable).
 *   - 'none' (gitleaks was absent at install) → run the dependency-free **pure-Node fallback scanner**
 *     below, so the gate no longer degrades to a silent skip (closes Debt#3). The fallback honours a
 *     `.secrets.baseline` (permanent known findings) and an expiry `allowlist.yaml` (temporary
 *     suppressions that FAIL the gate once expired), and scans only added lines in `--staged` mode.
 *
 * Modes (fallback tier):
 *   --staged        scan added (+) lines of the staged diff (pre-commit gate).
 *   <file> [file…]  scan the named files (CLI / marquee / test use).
 *   (no args)       detect mode — scan every git-tracked text file.
 *
 * Config seams (ENV-first via seam(), safe inline defaults — no config.json edit required):
 *   security.allowlistPath  (env KAIZEN_ALLOWLIST_PATH)  default .harness/security/allowlist.yaml
 *   security.baselinePath   (env KAIZEN_BASELINE_PATH)   default .harness/security/.secrets.baseline
 */
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig, seam } from '../lib/config.mjs';
import { repoRoot as gitRoot, git } from '../lib/repo.mjs';
import { commandExists } from '../lib/platform.mjs';

/**
 * Ruleset, ordered specific → generic. `group` picks the secret value from a capture group;
 * `minEntropy` (Shannon bits/char) gates the two false-positive-prone rules. A more-specific rule
 * that claims a span suppresses overlapping generic matches on the same span (see scanLine).
 */
export const RULES = [
  { id: 'aws-access-key', re: /\bA(?:KIA|SIA|GPA|IDA|ROA|IPA|NPA|NVA|CCA)[0-9A-Z]{16}\b/g },
  { id: 'private-key', re: /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----/g },
  { id: 'github-token', re: /\bgh[pousr]_[0-9A-Za-z]{36,255}\b/g },
  { id: 'slack-token', re: /\bxox[baprs]-[0-9A-Za-z][0-9A-Za-z-]{9,}\b/g },
  {
    id: 'generic-assignment',
    re: /(?:api[_-]?key|secret|token|passwd|password|access[_-]?key|client[_-]?secret|auth[_-]?token)["']?\s*[:=]\s*["']([A-Za-z0-9/+._=-]{16,})["']/gi,
    group: 1,
    minEntropy: 3.0,
    requireMixed: true, // real tokens mix letters+digits; excludes prose placeholders ("changeme-please")
  },
  { id: 'high-entropy-base64', re: /\b[A-Za-z0-9+/]{40,}={0,2}\b/g, minEntropy: 4.5 },
];

/** Shannon entropy (bits/char) of a string. */
export function shannon(s) {
  if (!s) return 0;
  const freq = Object.create(null);
  for (const c of s) freq[c] = (freq[c] || 0) + 1;
  let e = 0;
  for (const c in freq) { const p = freq[c] / s.length; e -= p * Math.log2(p); }
  return e;
}

/** Stable, path- AND line-independent fingerprint: sha256(rule \0 value). */
export function fingerprint(rule, value) {
  return createHash('sha256').update(`${rule}\0${value}`).digest('hex');
}

/** Redact a secret for safe log output — never print the full value. */
export function redact(v) {
  return v.length <= 6 ? '***' : `${v.slice(0, 3)}…${v.slice(-2)} (${v.length} chars)`;
}

/**
 * Scan a single line, returning [{ rule, value }]. More-specific rules win overlapping spans;
 * entropy-gated rules skip low-entropy matches (placeholders, dictionary words).
 */
export function scanLine(line) {
  return scanLineWithRules(line, RULES);
}

/** Scan one line with an explicit subset of the shared rules (prompt hooks use this seam). */
export function scanLineWithRules(line, rules) {
  const hits = [];
  const taken = []; // accepted [start,end) spans
  for (const rule of rules) {
    rule.re.lastIndex = 0;
    let m;
    while ((m = rule.re.exec(line)) !== null) {
      const full = m[0];
      if (full.length === 0) { rule.re.lastIndex++; continue; }
      const value = rule.group ? m[rule.group] : full;
      const start = m.index;
      const end = start + full.length;
      if (taken.some(([s, e]) => start < e && end > s)) continue; // claimed by a more-specific rule
      // Subresource-Integrity digests (`sha512-<base64>` in package-lock.json / yarn.lock /
      // pnpm-lock.yaml `integrity` fields) are PUBLIC content hashes, not secrets — but they trip the
      // generic high-entropy-base64 rule on every npm lockfile, which would fail-close `git push` on
      // essentially any Node repo. Exempt a base64 run immediately preceded by an SRI algo prefix.
      // Scoped to this one generic rule: a real token elsewhere (e.g. creds in a `resolved` URL) is
      // still caught, and the specific rules above are untouched.
      // (allow any base64 chars the leading `\b` skipped, e.g. `sha512-+AbC…` / `sha512-/AbC…`)
      if (rule.id === 'high-entropy-base64' && /(?:sha1|sha224|sha256|sha384|sha512)-[A-Za-z0-9+/=]*$/.test(line.slice(0, start))) continue;
      if (rule.minEntropy && shannon(value) < rule.minEntropy) continue;
      if (rule.requireMixed && !(/[0-9]/.test(value) && /[A-Za-z]/.test(value))) continue;
      hits.push({ rule: rule.id, value });
      taken.push([start, end]);
    }
  }
  return hits;
}

/** Scan multi-line text → [{ file, line, rule, value, fingerprint }]. */
export function scanText(text, file) {
  const findings = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    for (const h of scanLine(lines[i])) {
      findings.push({ file, line: i + 1, rule: h.rule, value: h.value, fingerprint: fingerprint(h.rule, h.value) });
    }
  }
  return findings;
}

/**
 * Load `.secrets.baseline` (JSON: { version, secrets: { <fingerprint>: {...} } }).
 * Missing file → empty set (graceful). Malformed → error (caller fails closed).
 */
export function loadBaseline(root, baselinePath) {
  const p = path.isAbsolute(baselinePath) ? baselinePath : path.join(root, baselinePath);
  if (!existsSync(p)) return { fingerprints: new Set(), error: null };
  try {
    const data = JSON.parse(readFileSync(p, 'utf8')) || {};
    return { fingerprints: new Set(Object.keys(data.secrets || {})), error: null };
  } catch (e) {
    return { fingerprints: new Set(), error: `malformed baseline ${baselinePath}: ${e.message}` };
  }
}

function unquote(v) {
  const t = v.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) return t.slice(1, -1);
  return t;
}

/**
 * Minimal YAML-subset parser for a top-level list of flat objects — sufficient for allowlist.yaml
 * (no nesting, no anchors). `- key: value` opens an entry; indented `key: value` extends it.
 * Comment (`#`) and blank lines are ignored.
 */
export function parseAllowlist(text) {
  const entries = [];
  let cur = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\t/g, '  ');
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const item = /^\s*-\s*(.*)$/.exec(line);
    if (item) {
      if (cur) entries.push(cur);
      cur = {};
      const kv = /^([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(item[1]);
      if (kv) cur[kv[1]] = unquote(kv[2]);
      continue;
    }
    const kv = /^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(line);
    if (kv && cur) cur[kv[1]] = unquote(kv[2]);
  }
  if (cur) entries.push(cur);
  return entries;
}

/**
 * Split allowlist entries into { active (fingerprints to suppress), expired, malformed }.
 * An entry needs a fingerprint AND a parseable `expires:` date; missing either → malformed
 * (fail closed). Expired (expires < now) → FAILS the gate. Otherwise → active suppression.
 */
export function evalAllowlist(entries, now) {
  const active = new Set();
  const expired = [];
  const malformed = [];
  for (const e of entries) {
    const exp = e.expires ? Date.parse(e.expires) : NaN;
    if (!e.fingerprint || !e.expires || Number.isNaN(exp)) { malformed.push(e); continue; }
    if (exp < now) expired.push(e);
    else active.add(e.fingerprint);
  }
  return { active, expired, malformed };
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
      const m = /\+(\d+)/.exec(raw);
      lineNo = m ? parseInt(m[1], 10) : 0;
    } else if (raw.startsWith('+')) {
      out.push({ file, line: lineNo, text: raw.slice(1) });
      lineNo++;
    }
  }
  return out;
}

/** Detect mode: scan every git-tracked text file (skips binary and >1 MiB blobs). */
function scanTrackedFiles(root) {
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
    findings.push(...scanText(content, rel));
  }
  return findings;
}

/** Run gitleaks (legacy tier). Returns exit code. */
function runGitleaks(root, staged) {
  if (!commandExists('gitleaks', ['version'])) {
    console.error('✗ secret-scan: gitleaks configured but not installed — fail closed. Install gitleaks or run `kaizen doctor --fix`.');
    return 1;
  }
  const args = staged ? ['protect', '--staged', '--redact', '--no-banner'] : ['detect', '--redact', '--no-banner'];
  const r = spawnSync('gitleaks', args, { cwd: root, stdio: 'inherit' });
  if (r.status !== 0) { console.error('✗ secret-scan: gitleaks found potential secrets (blocked)'); return 1; }
  console.error('✓ secret-scan: clean');
  return 0;
}

export function main(argv, opts = {}) {
  const now = opts.now ?? Date.now();
  const root = opts.root ?? gitRoot();
  const cfg = loadConfig(root);
  const scanner = cfg.security?.secretScanner || 'none';
  const staged = argv.includes('--staged');

  if (scanner === 'gitleaks') return runGitleaks(root, staged);
  if (scanner !== 'none') { console.error(`✗ secret-scan: unknown scanner "${scanner}"`); return 1; }

  // --- pure-Node fallback tier (scanner === 'none') ---
  const allowlistPath = seam('KAIZEN_ALLOWLIST_PATH', cfg.security?.allowlistPath, '.harness/security/allowlist.yaml');
  const baselinePath = seam('KAIZEN_BASELINE_PATH', cfg.security?.baselinePath, '.harness/security/.secrets.baseline');

  const baseline = loadBaseline(root, baselinePath);
  if (baseline.error) { console.error(`✗ secret-scan: ${baseline.error} (fail closed)`); return 1; }

  const alFile = path.isAbsolute(allowlistPath) ? allowlistPath : path.join(root, allowlistPath);
  let alEntries = [];
  if (existsSync(alFile)) {
    try { alEntries = parseAllowlist(readFileSync(alFile, 'utf8')); }
    catch (e) { console.error(`✗ secret-scan: malformed allowlist ${allowlistPath}: ${e.message} (fail closed)`); return 1; }
  }
  const al = evalAllowlist(alEntries, now);

  let failed = false;
  if (al.malformed.length) {
    console.error(`✗ secret-scan: ${al.malformed.length} allowlist entr${al.malformed.length === 1 ? 'y' : 'ies'} missing fingerprint/expires — fail closed.`);
    failed = true;
  }
  for (const e of al.expired) {
    console.error(`✗ secret-scan: allowlist entry EXPIRED ${e.expires} (fingerprint ${String(e.fingerprint).slice(0, 12)}…) — rotate the secret and remove the entry.`);
    failed = true;
  }

  // Gather findings for the requested mode.
  const fileArgs = argv.filter((a) => !a.startsWith('--'));
  let findings = [];
  if (fileArgs.length) {
    for (const f of fileArgs) {
      const abs = path.isAbsolute(f) ? f : path.join(root, f);
      if (!existsSync(abs)) { console.error(`✗ secret-scan: no such file ${f}`); return 1; }
      findings.push(...scanText(readFileSync(abs, 'utf8'), f));
    }
  } else if (staged) {
    for (const { file, line, text } of stagedAddedLines(root)) {
      for (const h of scanLine(text)) {
        findings.push({ file, line, rule: h.rule, value: h.value, fingerprint: fingerprint(h.rule, h.value) });
      }
    }
  } else {
    findings = scanTrackedFiles(root);
  }

  const active = findings.filter((f) => !baseline.fingerprints.has(f.fingerprint) && !al.active.has(f.fingerprint));
  if (active.length) {
    console.error(`✗ secret-scan: ${active.length} potential secret(s) found (pure-Node fallback):`);
    for (const f of active) console.error(`  ${f.file}:${f.line} [${f.rule}] ${redact(f.value)}  fingerprint=${f.fingerprint}`);
    console.error('  → rotate & remove, or record the fingerprint in .harness/security/.secrets.baseline (permanent) or allowlist.yaml (temporary, with expiry).');
    failed = true;
  }

  if (failed) return 1;
  console.error('✓ secret-scan: clean (pure-Node fallback)');
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
