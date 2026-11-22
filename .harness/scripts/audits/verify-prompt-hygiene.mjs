#!/usr/bin/env node
/**
 * @description Prompt-hygiene gate (H2-3, ported from Harness² `BenchPrompts` constructor
 * validation + `ANSWER_FREE` / `EVIDENCE_BOUNDARY` mission headers). A prompt that addresses a
 * grader/judge must never name the grading apparatus — "Say what the practitioner needs" — and
 * reviewer prompts must carry explicit answer-free / evidence-is-data headers so the reviewer
 * cannot be steered by embedded instructions.
 *
 * SCOPE GUARD (load-bearing): the forbidden-phrase scan applies to GRADER-ADDRESSED prompt
 * sections ONLY — a markdown section whose own header addresses the grader/judge
 * (`GRADER_HEADER_RE`). Plan prose, test names, and gate IDs are never scanned: content with no
 * grader-addressed header passes vacuously, so `docs/plans/*.md` (which legitimately scores plans
 * 0–100) and `core.gates.json` can never false-fail this gate.
 *
 * Pure core (`checkPromptHygiene`) + a thin CLI that scans staged subagent/skill prompts
 * (or `--file <path>`). Forbidden-phrase hits are ERRORS (exit 1); missing ANSWER_FREE /
 * EVIDENCE_IS_DATA headers on reviewer prompts are WARNINGS (advisory until prompts are
 * retrofitted — pass `--advisory` to demote errors to warnings for warn-first landing).
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot, stagedPaths, readRepoFile } from '../lib/repo.mjs';

/** Words the grading apparatus uses — forbidden inside grader-addressed prompt sections. */
export const FORBIDDEN = ['benchmark', 'evaluation', 'grader', 'rubric', 'score'];

/**
 * A markdown ATX header that ADDRESSES the grader/judge as its audience (as opposed to merely
 * mentioning scores or rubrics in passing). Only the body under such a header is in scope for
 * the forbidden-phrase scan — so a plan header like "# Score the plan 0-100" is NOT
 * grader-addressed and plan prose can never false-fail.
 */
export const GRADER_HEADER_RE = /^#{1,6}\s+.*\b(grader|grading|judge|judging)\b.*$/im;

/** Hygiene headers required (advisory) on reviewer-type prompts. */
export const HYGIENE_HEADERS = ['ANSWER_FREE', 'EVIDENCE_IS_DATA'];

/** 1-based line number of index `pos`. */
function lineAt(src, pos) {
  let line = 1;
  for (let i = 0; i < pos && i < src.length; i++) if (src[i] === '\n') line++;
  return line;
}

/**
 * Split markdown into `{ header, headerLine, body, bodyStartLine }` sections by ATX headers.
 * Content before the first header belongs to a headerless section (never grader-addressed).
 */
export function splitSections(content) {
  const lines = content.split('\n');
  const sections = [];
  let cur = { header: null, headerLine: 0, body: [], bodyStartLine: 1 };
  lines.forEach((l, i) => {
    if (/^#{1,6}\s/.test(l)) {
      sections.push(cur);
      cur = { header: l, headerLine: i + 1, body: [], bodyStartLine: i + 2 };
    } else {
      cur.body.push(l);
    }
  });
  sections.push(cur);
  return sections.map((s) => ({ ...s, body: s.body.join('\n') }));
}

/** True iff a section header addresses the grader/judge (scope-guard predicate). */
export function isGraderAddressed(header) {
  if (!header) return false;
  GRADER_HEADER_RE.lastIndex = 0;
  return GRADER_HEADER_RE.test(header);
}

/**
 * Scan `text` for whole-word, case-insensitive FORBIDDEN hits.
 * @returns {{line:number, phrase:string}[]} line offsets relative to `baseLine`.
 */
export function scanForbidden(text, baseLine = 1) {
  const hits = [];
  for (const phrase of FORBIDDEN) {
    const re = new RegExp(`\\b${phrase}\\b`, 'gi');
    let m;
    while ((m = re.exec(text)) !== null) {
      let line = baseLine;
      for (let i = 0; i < m.index && i < text.length; i++) if (text[i] === '\n') line++;
      hits.push({ line, phrase: m[0].toLowerCase() });
    }
  }
  return hits.sort((a, b) => a.line - b.line || a.phrase.localeCompare(b.phrase));
}

/** True iff `rel` is a reviewer-type prompt (by filename or `name:` frontmatter). */
export function isReviewerPrompt(rel, content) {
  const base = path.basename(rel);
  if (/^(adversarial-)?reviewer\.md$/.test(base)) return true;
  const fm = /^---\n([\s\S]*?)\n---/.exec(content);
  if (fm && /^\s*name\s*:\s*(adversarial-)?reviewer\s*$/m.test(fm[1])) return true;
  return false;
}

/**
 * Core check over already-loaded prompt content.
 * @param {string} content prompt file text
 * @param {{fileLabel?:string}} [ctx]
 * @returns {{ok:boolean, errors:string[], warnings:string[]}}
 */
export function checkPromptHygiene(content, ctx = {}) {
  const label = ctx.fileLabel || 'prompt';
  const errors = [];
  const warnings = [];

  // --- forbidden phrases: grader-addressed sections ONLY (scope guard) ---
  for (const sec of splitSections(content)) {
    if (!isGraderAddressed(sec.header)) continue;
    for (const hit of scanForbidden(sec.body, sec.bodyStartLine)) {
      errors.push(
        `${label}:${hit.line}: grader-addressed section (${sec.header.trim()}) names the grading apparatus ("${hit.phrase}") — say what the practitioner needs instead`,
      );
    }
  }

  // --- hygiene headers on reviewer prompts (advisory: warn, never fail) ---
  if (isReviewerPrompt(label, content)) {
    for (const h of HYGIENE_HEADERS) {
      if (!content.includes(h)) {
        warnings.push(
          `${label}: reviewer prompt lacks the ${h} header — add it so the reviewer stays answer-free / treats evidence as data, not instructions`,
        );
      }
    }
  }

  return { ok: errors.length === 0, errors, warnings };
}

/**
 * Which staged paths are prompts this gate must validate: `.md` under the subagent or skill
 * prompt trees. Pure (no git) so it is unit-testable. Explicit `--file` bypasses scoping.
 */
export function selectPromptPaths(paths) {
  return paths.filter(
    (p) =>
      p.endsWith('.md') &&
      (p.startsWith('.harness/subagents/') ||
        p.includes('/skills/') ||
        p.startsWith('skills/')),
  );
}

/** CLI: check staged prompt files, or a --file. Exit 1 on any error (0 with --advisory). */
export function main(argv) {
  const args = argv || [];
  const advisory = args.includes('--advisory');
  const fileFlag = (() => {
    const i = args.indexOf('--file');
    return i >= 0 ? args[i + 1] : null;
  })();

  const root = gitRoot();
  const targets = fileFlag ? [fileFlag] : selectPromptPaths(stagedPaths());
  if (targets.length === 0) return 0;

  let failed = 0;
  for (const rel of targets) {
    const content = fileFlag
      ? existsSync(rel)
        ? readFileSync(rel, 'utf8')
        : ''
      : readRepoFile(root, rel) || '';
    const res = checkPromptHygiene(content, { fileLabel: rel });
    for (const w of res.warnings) console.error(`! ${w}`);
    if (advisory) {
      for (const e of res.errors) console.error(`! ${e} (advisory — would block once promoted)`);
    } else {
      for (const e of res.errors) console.error(`✗ ${e}`);
      if (!res.ok) failed++;
    }
  }
  if (failed > 0) {
    console.error(`✗ prompt-hygiene: ${failed} prompt file(s) address the grader by name — reword to practitioner needs.`);
    return 1;
  }
  console.error(`✓ prompt-hygiene: ${targets.length} prompt file(s) clean`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
