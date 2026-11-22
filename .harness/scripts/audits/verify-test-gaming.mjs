#!/usr/bin/env node
/**
 * @description Test-gaming detection gate (P0-3). A suite can report green while asserting
 * nothing: `.only`-scoped tests hide the rest of the suite, skips dodge coverage, empty or
 * assert-free bodies are theatre, tautological asserts (`assert.ok(true)`) always pass.
 * This gate scans STAGED test files for those patterns and fails closed.
 *
 * kaizen is dependency-free (no JS parser), so detection is a lexical scan over a
 * comment/string-BLANKED copy of the source (offsets + newlines preserved) with brace-matched
 * test-block extraction. Blanking string/template/comment content is load-bearing: it makes the
 * detector self-safe — a test file that embeds `test.only` / `assert.ok(true)` as *string
 * fixtures* (exactly this gate's own unit tests) is not flagged, because those live inside
 * blanked string literals.
 *
 * Pure core `detectGaming(source, filename)` + a thin CLI that scans staged test files
 * (or `--file <path>`). Rules: only | skip-unjustified | empty-body | no-assert | tautology.
 *
 * Mirrors the pure-core + thin-CLI + fail-closed shape of verify-secrets.mjs / verify-plan-evidence.mjs.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot, stagedPaths, readRepoFile } from '../lib/repo.mjs';

/** A repo-relative path that is a test file (node --test conventions). */
export function isTestFile(rel) {
  return /(?:^|\/)test\//.test(rel) ? /\.[cm]?js$/.test(rel) : /\.(test|spec)\.[cm]?js$/.test(rel);
}

/**
 * Return a same-length copy of `src` with the CONTENT of line/block comments, single/double
 * quoted strings and template literals replaced by spaces. Newlines are preserved so line
 * numbers stay accurate; escapes (`\'`, `` \` ``) are handled. Everything else is code.
 */
export function blankNonCode(src) {
  const out = new Array(src.length);
  const n = src.length;
  let i = 0;
  const blank = (j) => (src[j] === '\n' ? '\n' : ' ');
  while (i < n) {
    const c = src[i];
    const c2 = i + 1 < n ? src[i + 1] : '';
    if (c === '/' && c2 === '/') {
      while (i < n && src[i] !== '\n') { out[i] = ' '; i++; }
      continue;
    }
    if (c === '/' && c2 === '*') {
      out[i] = ' '; out[i + 1] = ' '; i += 2;
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) { out[i] = blank(i); i++; }
      if (i < n) { out[i] = ' '; out[i + 1] = ' '; i += 2; }
      continue;
    }
    if (c === "'" || c === '"' || c === '`') {
      const q = c;
      out[i] = ' '; i++;
      while (i < n) {
        if (src[i] === '\\') { out[i] = ' '; if (i + 1 < n) out[i + 1] = blank(i + 1); i += 2; continue; }
        if (src[i] === q) { out[i] = ' '; i++; break; }
        out[i] = blank(i); i++;
      }
      continue;
    }
    out[i] = c; i++;
  }
  return out.join('');
}

/** Match a bracket pair (`(` / `{`) starting at `open` (index of the opener) in blanked code. */
function matchBracket(s, open) {
  const close = s[open] === '(' ? ')' : '}';
  const opener = s[open];
  let depth = 0;
  for (let i = open; i < s.length; i++) {
    if (s[i] === opener) depth++;
    else if (s[i] === close) { depth--; if (depth === 0) return i; }
  }
  return -1;
}

/** 1-based line number of index `pos`. */
function lineAt(src, pos) {
  let line = 1;
  for (let i = 0; i < pos && i < src.length; i++) if (src[i] === '\n') line++;
  return line;
}

/**
 * Detect test-gaming patterns in a single source string.
 * @param {string} source raw file text
 * @param {string} [filename] for messages (optional)
 * @returns {{findings: {line:number, rule:string, message:string}[]}}
 */
export function detectGaming(source, filename = '<source>') {
  const code = blankNonCode(source);
  const findings = [];
  const add = (line, rule, message) => findings.push({ line, rule, message });

  // --- only: hides the rest of the suite (highest-signal gaming) --------------------------
  for (const m of code.matchAll(/\b(?:test|it|describe)\s*\.\s*only\b/g)) {
    add(lineAt(source, m.index), 'only', `${m[0].trim()} scopes the run — hides the rest of the suite`);
  }
  for (const m of code.matchAll(/\bonly\s*:\s*true\b/g)) {
    add(lineAt(source, m.index), 'only', '{ only: true } scopes the run — hides the rest of the suite');
  }

  // --- skip without justification ---------------------------------------------------------
  const srcLines = source.split('\n');
  // kind: 'modifier' = test/it/describe.skip (its 1st string arg is a TITLE, not a reason);
  //       'tskip'    = t.skip('reason')      (its string arg IS the reason);
  //       'option'   = { skip: true }        (bare true — no reason).
  const skipByIdx = new Map();
  const patterns = [
    ['modifier', /\b(?:test|it|describe)\s*\.\s*skip\b/g],
    ['tskip', /\bt\s*\.\s*skip\s*\(/g],
    ['option', /\bskip\s*:\s*true\b/g],
  ];
  for (const [kind, re] of patterns) {
    for (const m of code.matchAll(re)) if (!skipByIdx.has(m.index)) skipByIdx.set(m.index, kind);
  }
  for (const idx of [...skipByIdx.keys()].sort((a, b) => a - b)) {
    const kind = skipByIdx.get(idx);
    const line = lineAt(source, idx);
    const orig = srcLines[line - 1] || '';
    const prev = srcLines[line - 2] || '';
    const hasComment = /\/\/\s*\S*[A-Za-z]/.test(orig) || /^\s*\/\/\s*\S*[A-Za-z]/.test(prev) || /\/\*.*[A-Za-z].*\*\//.test(orig);
    // Only t.skip('reason') has a reason-bearing string arg; a modifier's string arg is the title.
    const hasReason = kind === 'tskip' && /\.\s*skip\s*\(\s*['"`][^'"`]*[A-Za-z]/.test(orig);
    if (!hasComment && !hasReason) {
      add(line, 'skip-unjustified', 'skipped test without a justification (add a `{ skip: "reason" }` / `t.skip("reason")` reason or a `// why` comment)');
    }
  }

  // --- empty-body / no-assert / tautology over extracted test blocks ----------------------
  for (const m of code.matchAll(/\b(?:test|it)\s*(?:\.\s*\w+)?\s*\(/g)) {
    const openParen = m.index + m[0].length - 1;
    const closeParen = matchBracket(code, openParen);
    if (closeParen === -1) continue;
    const args = code.slice(openParen + 1, closeParen);
    const argsBase = openParen + 1;

    // Locate the callback body: first `{` after an `=>` or a `function(...)`, else concise arrow expr.
    let bodyText = null;
    const arrowBrace = /=>\s*\{/.exec(args);
    const fnBrace = /function\b[^{]*\{/.exec(args);
    const braceMatch = arrowBrace || fnBrace;
    if (braceMatch) {
      const braceRel = args.indexOf('{', braceMatch.index);
      const braceAbs = argsBase + braceRel;
      const end = matchBracket(code, braceAbs);
      if (end !== -1) bodyText = code.slice(braceAbs + 1, end);
    } else {
      const arrow = args.indexOf('=>');
      if (arrow !== -1) bodyText = args.slice(arrow + 2); // concise arrow: `=> expr`
    }
    if (bodyText == null) continue;

    const line = lineAt(source, m.index);
    // skip is scored by its own rule — don't double-report a skipped test as empty/assert-free.
    const isSkip = /\.\s*skip\b/.test(m[0]) || /\bskip\s*:\s*true\b/.test(args) || /\bt\s*\.\s*skip\s*\(/.test(bodyText);
    if (isSkip) continue;
    const nested = /\b(?:test|it)\s*(?:\.\s*\w+)?\s*\(/.test(bodyText); // suite/parent — subtests scored on their own
    const hasAssert = /\bassert\b|\bt\s*\.\s*assert\b/.test(bodyText);

    if (braceMatch && bodyText.trim() === '') {
      add(line, 'empty-body', 'test has an empty body — it asserts nothing');
    } else if (!nested && !hasAssert) {
      add(line, 'no-assert', 'test body contains no assert call — it can never fail');
    }
  }

  // --- tautological asserts (scanned on blanked code → self-safe) -------------------------
  for (const m of code.matchAll(/\bassert\s*(?:\.\s*ok)?\s*\(\s*(?:true|1)\s*\)/g)) {
    add(lineAt(source, m.index), 'tautology', 'tautological assert (always true) — asserts nothing');
  }
  for (const m of code.matchAll(/\bassert\s*\.\s*(?:equal|strictEqual|deepEqual|deepStrictEqual)\s*\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)/g)) {
    if (m[1].trim() === m[2].trim()) {
      add(lineAt(source, m.index), 'tautology', `tautological assert (${m[1].trim()} === itself) — asserts nothing`);
    }
  }

  // Dedupe identical (line, rule, message); sort by line.
  const seen = new Set();
  const unique = findings.filter((f) => {
    const k = `${f.line}|${f.rule}|${f.message}`;
    if (seen.has(k)) return false;
    seen.add(k); return true;
  }).sort((a, b) => a.line - b.line || a.rule.localeCompare(b.rule));
  void filename;
  return { findings: unique };
}

/** CLI: scan staged test files (`--staged`) or a single `--file <path>`. Exit 1 on any finding. */
export function main(argv) {
  const root = gitRoot();
  const cfg = loadConfig(root);
  if (cfg.audits?.testGaming?.enabled === false) return 0; // opt-out (default on)

  const fileFlag = (() => { const i = argv.indexOf('--file'); return i >= 0 ? argv[i + 1] : null; })();
  let targets;
  if (fileFlag) targets = [fileFlag];
  else targets = stagedPaths().filter(isTestFile);

  if (targets.length === 0) return 0;

  let total = 0;
  for (const rel of targets) {
    const content = fileFlag ? (existsSync(rel) ? readFileSync(rel, 'utf8') : '') : (readRepoFile(root, rel) || '');
    const { findings } = detectGaming(content, rel);
    for (const f of findings) {
      console.error(`✗ ${rel}:${f.line}: [${f.rule}] ${f.message}`);
      total++;
    }
  }
  if (total > 0) {
    console.error(`✗ test-gaming: ${total} finding(s) — gamed tests block the commit. Fix the tests or justify skips.`);
    return 1;
  }
  console.error(`✓ test-gaming: ${targets.length} test file(s) clean`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
