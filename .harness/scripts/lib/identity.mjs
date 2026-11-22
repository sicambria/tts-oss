/**
 * @description Host/personal-identity leak primitives — the shared core behind two consumers that
 * MUST agree (else one emits what the other blocks):
 *   - verify-identity.mjs  (gate)   DETECTS host-unique identifiers in committed/staged text.
 *   - memory-capture.mjs    (writer) REDACTS them out of episodic journals at write time.
 *
 * Scope is deliberately narrow — "host-unique IDs", not all PII:
 *   1. Structural (universal, deterministic, CI-safe): an absolute home path carrying a concrete OS
 *      username segment — /home/<user>/, /Users/<user>/, \Users\<user>\. This is THE guarantee: it
 *      fires on any machine and in CI regardless of who ran the commit.
 *   2. Runtime host fingerprint (best-effort bonus, only protects the machine it runs on): the CURRENT
 *      user's `os.userInfo().username`, `os.homedir()`, and `os.hostname()`, matched as whole tokens.
 *      In CI the user is `runner`, so this layer adds nothing there — the structural rule is the floor.
 *
 * Non-goals: bare random UUIDs/session ids (not host- or person-identifying, huge false-positive
 * surface), and PUBLISHED authorship (a project's own GitHub handle in repo URLs / LICENSE) — that is
 * intentional and must NOT trip this gate. The rules below only match filesystem-username shapes and
 * the running host's own tokens, so a published handle that differs from the OS user never matches.
 */
import os from 'node:os';
import { createHash } from 'node:crypto';

/**
 * Usernames that are documentation placeholders, not real host leaks. A `/home/user/…` in a README
 * is an example, not a fingerprint — skip it (both when detecting and when deciding a token is
 * distinctive enough to redact). Lowercased compare.
 */
export const PLACEHOLDER_USERS = new Set([
  'user', 'username', 'you', 'me', 'us', 'root', 'home', 'someone', 'somebody',
  'example', 'foo', 'bar', 'baz', 'test', 'demo', 'name', 'youruser', 'yourname',
]);

/**
 * Structural home-path rule. Captures the username segment after /home/, /Users/, or \Users\.
 * The username class excludes '<' and '~', so placeholders like `/home/<user>/` and `~/…` never match.
 * Lookahead for a following separator keeps the match to the username (not the whole path tail).
 */
export const HOME_PATH_RE = /(?:\/home\/|\/Users\/|\\Users\\)([A-Za-z_][A-Za-z0-9_.-]*)(?=[/\\])/g;

/** A token is a real fingerprint (worth matching) only if it's concrete, not a generic placeholder. */
export function isDistinctiveToken(tok) {
  if (!tok || typeof tok !== 'string') return false;
  if (tok.length < 3) return false; // too short → matches everywhere, all noise
  if (PLACEHOLDER_USERS.has(tok.toLowerCase())) return false;
  return /^[A-Za-z0-9._-]+$/.test(tok); // simple token; anything exotic isn't a username/hostname
}

/**
 * Resolve this host's fingerprints, injectable for deterministic tests. `os.userInfo()` THROWS on
 * passwd-less containers, so every lookup is wrapped and degrades to null (structural rule still holds).
 * Pass any field in `opts` to override; pass `null` explicitly to force-disable that field.
 */
export function hostFingerprints(opts = {}) {
  const pick = (val, fn) => {
    if (val !== undefined) return val || null;
    try { return fn() || null; } catch { return null; }
  };
  const host = pick(opts.host, () => os.hostname());
  return {
    user: pick(opts.user, () => os.userInfo().username),
    home: pick(opts.home, () => os.homedir()),
    // Bare short hostname only (drop the DNS domain: `box.local` → `box`).
    host: host ? host.split('.')[0] : null,
  };
}

/** Stable fingerprint (rule \0 value) so a finding can be baselined/allowlisted regardless of path/line. */
export function fingerprint(rule, value) {
  return createHash('sha256').update(`${rule}\0${value}`).digest('hex');
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Scan one line → [{ rule, value }]. More-specific spans win: the structural home-path rule claims
 * its span first, so the running user's token inside that same path is not double-reported.
 * @param {{user:string|null, home:string|null, host:string|null}} fp
 */
export function scanLine(line, fp = {}) {
  const hits = [];
  const taken = []; // accepted [start,end) spans

  // Rule 1 — structural home path (universal).
  HOME_PATH_RE.lastIndex = 0;
  let m;
  while ((m = HOME_PATH_RE.exec(line)) !== null) {
    const user = m[1];
    const start = m.index;
    const end = start + m[0].length;
    if (PLACEHOLDER_USERS.has(user.toLowerCase())) { taken.push([start, end]); continue; }
    hits.push({ rule: 'host-path', value: m[0] });
    taken.push([start, end]);
  }

  // Rules 2 & 3 — this host's own tokens as whole words (best-effort, machine-local).
  const tokenRules = [
    ['host-user', fp.user],
    ['host-name', fp.host],
  ];
  for (const [rule, tok] of tokenRules) {
    if (!isDistinctiveToken(tok)) continue;
    const re = new RegExp(`(?<![A-Za-z0-9])${escapeRegExp(tok)}(?![A-Za-z0-9])`, 'g');
    let mm;
    while ((mm = re.exec(line)) !== null) {
      const start = mm.index;
      const end = start + mm[0].length;
      if (taken.some(([s, e]) => start < e && end > s)) continue; // inside a claimed path span
      hits.push({ rule, value: tok });
      taken.push([start, end]);
    }
  }
  return hits;
}

/** Scan multi-line text → [{ file, line, rule, value, fingerprint }]. */
export function scanText(text, file, fp = {}) {
  const findings = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    for (const h of scanLine(lines[i], fp)) {
      findings.push({ file, line: i + 1, rule: h.rule, value: h.value, fingerprint: fingerprint(h.rule, h.value) });
    }
  }
  return findings;
}

/**
 * Inverse of detection — collapse this host's fingerprints OUT of a string so the writer never emits
 * what the gate would block. Order matters: the home prefix (most specific) first, then bare user, then
 * host. Guarded so a null/generic token is never substituted (which would corrupt unrelated text).
 *   $HOME/git/x                                         → ~/git/x
 *   ~/.claude/projects/-home-<user>-git-x/<id>.jsonl    → (already clean — the <user> slug is inert)
 */
export function redactHostPaths(str, fp = {}) {
  if (!str || typeof str !== 'string') return str;
  let out = str;
  if (fp.home && fp.home.length >= 2) {
    out = out.replaceAll(fp.home, '~');
  }
  if (isDistinctiveToken(fp.user)) {
    out = out.replace(new RegExp(`(?<![A-Za-z0-9])${escapeRegExp(fp.user)}(?![A-Za-z0-9])`, 'g'), '<user>');
  }
  if (isDistinctiveToken(fp.host)) {
    out = out.replace(new RegExp(`(?<![A-Za-z0-9])${escapeRegExp(fp.host)}(?![A-Za-z0-9])`, 'g'), '<host>');
  }
  return out;
}
