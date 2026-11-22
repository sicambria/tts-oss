#!/usr/bin/env node
/**
 * @description UserPromptSubmit hook for high-confidence credential formats. It intentionally uses a
 * narrower subset of the commit scanner because a false positive here discards the user's prompt.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot } from './lib/repo.mjs';
import { RULES, scanLineWithRules } from './audits/verify-secrets.mjs';

const PROMPT_RULE_IDS = new Set(['aws-access-key', 'github-token', 'slack-token', 'private-key']);
const PROMPT_RULES = RULES.filter((rule) => PROMPT_RULE_IDS.has(rule.id));
const BLOCK_MESSAGE = 'possible secret detected — remove the secret and re-type your prompt';

export function parsePromptInput(raw) {
  try {
    const value = JSON.parse(raw || '');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

export function scanPrompt(prompt, rules = PROMPT_RULES) {
  if (typeof prompt !== 'string' || !prompt) return [];
  return prompt.split(/\r?\n/).flatMap((line) => scanLineWithRules(line, rules));
}

export function main(argv = [], opts = {}) {
  const root = opts.root ?? gitRoot();
  let cfg;
  try {
    cfg = opts.config ?? loadConfig(root);
  } catch {
    return 0; // malformed harness config must not erase user input
  }
  if (cfg.security?.promptSecretScan === false) return 0;
  const raw = opts.raw ?? readFileSync(0, 'utf8');
  const payload = parsePromptInput(raw);
  if (scanPrompt(payload.prompt).length === 0) return 0;
  console.error(BLOCK_MESSAGE);
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
