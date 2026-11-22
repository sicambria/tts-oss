#!/usr/bin/env node
/**
 * @description Gate registry. Loads the core gate manifest plus any adapter manifests listed in
 * config.gates.adapters, and merges them per chain (core gates first, then adapter gates in order).
 * Data-driven so adapters register gates by dropping a `<name>.gates.json` in .harness/gates/ and
 * listing `<name>` in config.gates.adapters — no edits to core.
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

function loadManifest(root, name) {
  const p = path.join(root, '.harness', 'gates', `${name}.gates.json`);
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch (e) { throw new Error(`Bad gate manifest ${name}: ${e.message}`); }
}

/**
 * Resolve the ordered gate list for a chain across core + adapter manifests.
 * @param {string} root repo root
 * @param {object} config loaded config
 * @param {string} chain 'pre-commit'|'pre-push'|'guardrails'
 * @returns {Array<{id:string, run:string[], source:string}>}
 */
export function resolveChain(root, config, chain) {
  const manifests = [];
  const core = loadManifest(root, config.gates?.core || 'core');
  if (core) manifests.push({ src: 'core', m: core });
  for (const name of config.gates?.adapters || []) {
    const m = loadManifest(root, name);
    if (m) manifests.push({ src: name, m });
  }
  const gates = [];
  for (const { src, m } of manifests) {
    for (const g of (m.chains?.[chain] || [])) gates.push({ ...g, source: src });
  }
  return gates;
}
