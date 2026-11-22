#!/usr/bin/env node
/**
 * @description Harness-surface validators (H2-5, ported from Harness² `tree.py::validate` +
 * the form-over-content cost ladder). Three checks over the skill/harness surface:
 *
 *   1. skill trigger-line: every `skills/<name>/SKILL.md` must be named in the always-on docs —
 *      else warn with the exact trigger line to add (autotrigger-style suggestion).
 *   2. Jinja-brace ban: no `{{` in always-on markdown (template braces in always-on text break
 *      strict rendering and signal content that belongs in an on-demand component).
 *   3. script-exists: every script path referenced from a skill doc must exist on disk.
 *
 * ADVISORY-ONLY first cut: this gate WARNS (exit 0) and never fails closed — promotion to
 * fail-closed is a later wave after one dogfood cycle. `main()` returns 0 unconditionally
 * (bar usage errors); findings are `{rule, message}` warnings.
 *
 * Pure core (`checkHarnessSurface` over injected file lists + `checkHarnessSurfaceAt` over a
 * repo root) + a thin CLI. Zero model cost.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

/** Skill prompt trees scanned (repo-relative). The first that exists wins. */
export const SKILL_ROOTS = ['.claude/skills', 'skills'];

/** Always-on docs: prose paid on every turn, so the cost ladder applies here. */
export const ALWAYS_ON_DOCS = ['AGENTS.md', '.harness/memory/rules.md'];

/** A mention counts as a trigger only in one of these shapes (bare-word matches don't count). */
export function isTriggered(name, alwaysOnText) {
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`\\/${esc}\\b|skills\\/${esc}\\b|\\b${esc} skill\\b`, 'i').test(alwaysOnText);
}

/** The exact trigger line to add for an unreferenced skill (autotrigger-style suggestion). */
export function suggestTriggerLine(name, description) {
  const desc = (description || 'see the skill prompt for when to invoke it.').trim();
  return `- \`/${name}\`: ${desc}`;
}

/** First non-empty `description:` frontmatter line, or null. */
export function skillDescription(content) {
  const fm = /^---\n([\s\S]*?)\n---/.exec(content);
  if (!fm) return null;
  const m = /^\s*description\s*:\s*(.+?)\s*$/m.exec(fm[1]);
  return m ? m[1] : null;
}

/** 1-based line numbers of every `{{` occurrence. */
export function braceLines(content) {
  const out = [];
  content.split('\n').forEach((l, i) => {
    if (l.includes('{{')) out.push(i + 1);
  });
  return out;
}

const SCRIPT_REF = /(?:\.harness\/scripts|scripts)\/[A-Za-z0-9_./-]+\.(?:mjs|py)/g;

/** Script paths referenced from a skill doc (as written, repo-relative-or-rooted). */
export function scriptRefs(content) {
  return [...new Set(content.match(SCRIPT_REF) || [])];
}

/**
 * Check 1 — pure: which skill names lack a trigger-line mention in the always-on text.
 * @returns {{rule:string, message:string}[]} warnings
 */
export function skillTriggerCheck(skills, alwaysOnText) {
  const warnings = [];
  for (const { name, description } of skills) {
    if (!isTriggered(name, alwaysOnText)) {
      warnings.push({
        rule: 'skill-trigger',
        message: `skill "${name}" is never named in always-on docs — add this trigger line: ${suggestTriggerLine(name, description)}`,
      });
    }
  }
  return warnings;
}

/**
 * Check 2 — pure: `{{` occurrences in always-on markdown files.
 * @param {{rel:string, content:string}[]} files
 */
export function braceCheck(files) {
  const warnings = [];
  for (const { rel, content } of files) {
    for (const line of braceLines(content)) {
      warnings.push({
        rule: 'jinja-brace',
        message: `${rel}:${line}: always-on markdown contains "{{" — move templated content to an on-demand skill/script`,
      });
    }
  }
  return warnings;
}

/**
 * Check 3 — pure: skill-referenced scripts must exist (`exists` injects the filesystem).
 * @param {{rel:string, content:string}[]} skillDocs
 * @param {(rel:string) => boolean} exists
 */
export function scriptExistsCheck(skillDocs, exists) {
  const warnings = [];
  for (const { rel, content } of skillDocs) {
    for (const ref of scriptRefs(content)) {
      const rooted = ref.startsWith('.harness/') || ref.startsWith('scripts/') ? ref : null;
      if (rooted && !exists(rooted)) {
        warnings.push({
          rule: 'script-exists',
          message: `${rel}: references script "${ref}" which does not exist — ship it in the proposal or fix the reference`,
        });
      }
    }
  }
  return warnings;
}

/** List `{name, rel, content}` skills under the first existing SKILL_ROOTS entry. */
export function loadSkills(root) {
  for (const sr of SKILL_ROOTS) {
    const abs = path.join(root, sr);
    if (!existsSync(abs)) continue;
    const out = [];
    for (const ent of readdirSync(abs, { withFileTypes: true })) {
      if (!ent.isDirectory()) continue;
      const skillFile = path.join(abs, ent.name, 'SKILL.md');
      if (!existsSync(skillFile)) continue;
      const content = readFileSync(skillFile, 'utf8');
      out.push({ name: ent.name, rel: `${sr}/${ent.name}/SKILL.md`, content });
    }
    return out;
  }
  return [];
}

function readIf(root, rel) {
  try {
    return readFileSync(path.join(root, rel), 'utf8');
  } catch {
    return null;
  }
}

/**
 * Full surface check against a repo root. Never throws on missing files (absent
 * always-on docs / skill trees yield zero warnings, not errors).
 * @returns {{warnings:{rule:string, message:string}[]}}
 */
export function checkHarnessSurfaceAt(root) {
  const skills = loadSkills(root);
  const alwaysOnFiles = [];
  let alwaysOnText = '';
  for (const rel of ALWAYS_ON_DOCS) {
    const content = readIf(root, rel);
    if (content != null) {
      alwaysOnFiles.push({ rel, content });
      alwaysOnText += `\n${content}`;
    }
  }
  const skillDocs = skills.map(({ rel, content }) => ({ rel, content }));
  const warnings = [
    ...skillTriggerCheck(
      skills.map(({ name, content }) => ({ name, description: skillDescription(content) })),
      alwaysOnText,
    ),
    ...braceCheck(alwaysOnFiles),
    ...scriptExistsCheck(skillDocs, (rel) => existsSync(path.join(root, rel))),
  ];
  return { warnings };
}

/** CLI: print warnings, ALWAYS exit 0 (advisory-only first cut — never fail-closed). */
export function main(argv = []) {
  void argv;
  const root = gitRoot();
  const { warnings } = checkHarnessSurfaceAt(root);
  for (const w of warnings) console.error(`! harness-surface [${w.rule}]: ${w.message}`);
  console.error(
    warnings.length === 0
      ? '✓ harness-surface: skill surface clean (advisory)'
      : `~ harness-surface: ${warnings.length} advisory warning(s) — non-blocking (promotion to fail-closed is a later wave)`,
  );
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
