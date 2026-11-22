#!/usr/bin/env node
/**
 * @description slopcheck supply-chain gate (P1-7). An agent can slip a runtime dependency — or a
 * typosquat of a popular package (`lodahs`, `expresss`, `chak`) — into package.json. kaizen is
 * dependency-free, so the clean baseline is ZERO runtime deps; any addition deserves scrutiny.
 *
 * Two rules over `checkDeps(pkgJson, allowlist)` (pure):
 *   - typosquat: a dep name at edit-distance 1 from a curated popular-package list but not an exact
 *     match → BLOCK. This is a LOCAL heuristic (no network), so it fails hard.
 *   - unverified: any non-allowlisted runtime dep. Confirming a package's legitimacy needs the
 *     registry, which this gate does NOT contact — so it ABSTAINS (human_needed, non-zero) rather
 *     than silently passing, matching the honest-abstain contract in verify.mjs.
 *
 * Clean (exit 0) = no runtime deps, or every runtime dep allowlisted and no typosquat.
 * Violation (exit 1) = a typosquat, or an unverified dep (human_needed abstain). Never silent-pass.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

// Curated popular npm packages — typosquat targets. Not exhaustive; catches the common lures.
const POPULAR = [
  'react', 'react-dom', 'express', 'lodash', 'chalk', 'axios', 'commander', 'debug', 'dotenv',
  'moment', 'request', 'webpack', 'babel', 'eslint', 'jest', 'mocha', 'typescript', 'vue',
  'next', 'jquery', 'bluebird', 'colors', 'yargs', 'uuid', 'glob', 'rimraf', 'semver',
];

/**
 * Optimal String Alignment (Damerau-Levenshtein restricted) distance — counts an ADJACENT
 * transposition as a single edit, so both a doubled letter (`expresss`) and a swap (`lodahs`)
 * register at distance 1. Cheap: package names are short.
 */
function editDistance(a, b) {
  if (a === b) return 0;
  const m = a.length, n = b.length;
  const d = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) d[i][0] = i;
  for (let j = 0; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
  }
  return d[m][n];
}

/** Bare package name without a scope (`@scope/name` → `name`). */
function bareName(dep) {
  return dep.startsWith('@') && dep.includes('/') ? dep.slice(dep.indexOf('/') + 1) : dep;
}

/**
 * Analyze a parsed package.json for supply-chain slop.
 * @param {object} pkgJson parsed package.json
 * @param {string[]} [allowlist] dep names explicitly approved
 * @returns {{findings: {name:string, rule:string, severity:'block'|'human_needed', message:string}[]}}
 */
export function checkDeps(pkgJson, allowlist = []) {
  const allow = new Set(allowlist);
  const deps = {
    ...(pkgJson?.dependencies || {}),
    ...(pkgJson?.peerDependencies || {}),
    ...(pkgJson?.optionalDependencies || {}),
  };
  const findings = [];
  for (const name of Object.keys(deps)) {
    if (allow.has(name)) continue;
    const bare = bareName(name);
    const squat = POPULAR.find((p) => p !== bare && editDistance(bare, p) === 1);
    if (squat) {
      findings.push({ name, rule: 'typosquat', severity: 'block', message: `looks like a typosquat of "${squat}" (edit-distance 1)` });
    } else {
      findings.push({ name, rule: 'unverified', severity: 'human_needed', message: 'unverified runtime dependency — cannot confirm against the registry offline; add to slopcheck.allowlist after human review' });
    }
  }
  return { findings };
}

/** CLI: check repo package.json (or `--file <path>`). Exit 1 on any finding; never silent-pass. */
export function main(argv) {
  const root = gitRoot();
  const cfg = loadConfig(root);
  if (cfg.audits?.slopcheck?.enabled === false) return 0; // opt-out (default on)
  const allowlist = cfg.audits?.slopcheck?.allowlist || [];

  const fileFlag = (() => { const i = argv.indexOf('--file'); return i >= 0 ? argv[i + 1] : null; })();
  const pkgPath = fileFlag || path.join(root, 'package.json');
  if (!existsSync(pkgPath)) return 0; // no manifest → nothing to check

  let pkg;
  try {
    pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
  } catch (e) {
    console.error(`✗ slopcheck: cannot parse ${pkgPath}: ${e.message}`);
    return 1;
  }

  const { findings } = checkDeps(pkg, allowlist);
  if (findings.length === 0) {
    console.error('✓ slopcheck: no unverified runtime dependencies');
    return 0;
  }
  const blocks = findings.filter((f) => f.severity === 'block');
  const abstains = findings.filter((f) => f.severity === 'human_needed');
  for (const f of blocks) console.error(`✗ slopcheck: [${f.rule}] ${f.name} — ${f.message}`);
  for (const f of abstains) console.error(`✗ slopcheck: [human_needed] ${f.name} — ${f.message}`);
  if (blocks.length) console.error(`✗ slopcheck: ${blocks.length} suspected typosquat(s) — blocked.`);
  if (abstains.length) console.error(`✗ slopcheck: ${abstains.length} unverified dep(s) abstained (human_needed) — fail closed.`);
  return 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
