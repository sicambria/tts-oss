#!/usr/bin/env node
/**
 * @description Manifest↔CI drift guard (changemappers gate-wiring collector, generalized). The CI
 * backstop `kaizen-gate.yml` is the UN-BYPASSABLE anchor — `--no-verify` can defeat a local hook but not
 * a required CI job. But its steps are hand-listed YAML, decoupled from the gate manifest
 * `.harness/gates/core.gates.json`: add a gate to the manifest and it is silently left OUT of CI (the
 * Fellow-review C3 hole quietly recurs), with nothing to notice. This gate closes that drift.
 *
 * Contract: every gate id in the manifest chains must be enforced by the CI backstop — EITHER a step runs
 * its script directly, OR a `run-gates.mjs <chain>` step covers a chain the gate belongs to — except a
 * small, code-audited exemption set (`CI_EXEMPT_GATES`). It is the CI-side analogue of doctor's "never
 * silently orphan a gate", and the SURFACE-parity twin of `verify-script-parity` (which is TREE parity).
 *
 * Checks EVERY present backstop file — the shipped source of truth `.harness/ci/kaizen-gate.yml` (in the
 * dogfood tree, the `templates/core` payload, and every adopter install) AND `.github/workflows/kaizen-gate.yml`,
 * the file GitHub actually runs (init copies the source there; `verify-script-parity` mirrors `.harness/ci`
 * ↔ `templates/core` but does NOT cover `.github/workflows`, so this is the only guard on the running copy).
 * A gate dropped from EITHER the template or the running workflow is caught. All backstop files absent →
 * abstains OK (a forge adopter using the reduced `doctor + verify` backstop — doctor WARNs on a missing one).
 *
 * Pure core (`manifestGates`, `computeCiGateCoverage`) + a fail-closed CLI, mirroring the sibling audits.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { repoRoot as gitRoot } from '../lib/repo.mjs';

// Gates deliberately NOT wired into the CI backstop, each with a documented reason IN kaizen-gate.yml.
// (Empty after ratchet2: decision-log's staged same-commit-atomicity mode stays local-only BY
// CONSTRUCTION — CI never runs the bare scan, so the staged semantic needs no exemption entry —
// while its --range commit-range mode IS enforced via the push-range step in kaizen-gate.yml.
// The blanket exemption therefore narrowed to nothing: every manifest gate is CI-enforced.)
// This set must stay minimal: dropping a gate from the un-bypassable backstop must be a conscious,
// audited act (log a decision) — changing this set is a substantive, gated code edit, so that
// friction is the point.
//   - decision-log (staged mode): a staged same-commit-atomicity gate (an override and its decision
//     record must land in ONE commit); that does not map onto a multi-commit / squashed CI push range.
//     It stays a local pre-commit gate and is covered in CI by the --range step instead.
//     (See the header comment in .harness/ci/kaizen-gate.yml.)
export const CI_EXEMPT_GATES = new Set([]);

// The CI backstop files this guard holds to the manifest. Both are checked WHEN PRESENT: the shipped
// template (protects every adopter's payload) AND the file GitHub actually runs (init copies the template
// there). Forge files (.gitlab-ci.yml / bitbucket-pipelines.yml) are deliberately excluded — they use the
// reduced `doctor + verify` backstop, not per-gate steps, so a manifest-coverage check would false-fail.
export const CI_BACKSTOP_FILES = [
  '.harness/ci/kaizen-gate.yml',
  '.github/workflows/kaizen-gate.yml',
];

/** Collect gateId → {scripts:Set<string>, chains:Set<string>} from a parsed core.gates.json. */
export function manifestGates(manifest) {
  const gates = new Map();
  for (const [chain, steps] of Object.entries(manifest?.chains || {})) {
    for (const step of steps || []) {
      if (!step || !step.id) continue;
      const g = gates.get(step.id) || { scripts: new Set(), chains: new Set() };
      const script = (step.run || []).find((a) => typeof a === 'string' && a.endsWith('.mjs'));
      if (script) g.scripts.add(script);
      g.chains.add(chain);
      gates.set(step.id, g);
    }
  }
  return gates;
}

/**
 * Pure coverage check. A manifest gate is covered if the CI text runs its script directly, or runs a
 * `run-gates.mjs <chain>` step for a chain the gate belongs to.
 * @param {{manifest:object, ciText:string, exempt?:Set<string>}} args
 * @returns {{covered:Array<{id:string,via:string}>, missing:string[], exemptStale:string[]}}
 */
export function computeCiGateCoverage({ manifest, ciText, exempt = CI_EXEMPT_GATES }) {
  const gates = manifestGates(manifest);
  // Match against EXECUTABLE YAML only — drop full-line `# comment` lines so a gate NAMED in a comment
  // (e.g. the header explaining why decision-log is not wired) cannot read as falsely covered.
  const ci = String(ciText || '').split('\n').filter((l) => !/^\s*#/.test(l)).join('\n');
  // Chains CI runs wholesale via a `run-gates.mjs <chain>` step (covers every gate in that chain).
  const ciChains = new Set();
  for (const m of ci.matchAll(/run-gates\.mjs\s+(\S+)/g)) ciChains.add(m[1]);

  const covered = [];
  const missing = [];
  for (const [id, g] of gates) {
    if (exempt.has(id)) continue;
    const viaScript = [...g.scripts].find((s) => ci.includes(s));
    const viaChain = [...g.chains].find((c) => ciChains.has(c));
    if (viaScript) covered.push({ id, via: `step:${viaScript}` });
    else if (viaChain) covered.push({ id, via: `chain:${viaChain}` });
    else missing.push(id);
  }
  // An exempt id no longer present in the manifest is a stale exemption (rot) → WARN, never fail.
  const exemptStale = [...exempt].filter((id) => !gates.has(id));
  return { covered, missing, exemptStale };
}

/** CLI: fail-closed if any non-exempt manifest gate is missing from ANY present CI backstop file. */
export function main(argv = [], opts = {}) {
  const root = opts.root || gitRoot();
  const manifestPath = path.join(root, '.harness', 'gates', 'core.gates.json');

  if (!existsSync(manifestPath)) { console.log('✓ ci-gate-parity: no gate manifest — nothing to check'); return 0; }
  let manifest;
  try { manifest = JSON.parse(readFileSync(manifestPath, 'utf8')); }
  catch (e) { console.error(`✗ ci-gate-parity: cannot parse ${path.relative(root, manifestPath)}: ${e.message}`); return 1; }

  const present = CI_BACKSTOP_FILES.filter((rel) => existsSync(path.join(root, rel)));
  if (present.length === 0) { console.log('✓ ci-gate-parity: no kaizen-gate.yml backstop present — abstaining (forge/reduced-CI adopter; doctor WARNs on a missing CI backstop)'); return 0; }

  let failed = false;
  for (const rel of present) {
    const ciText = readFileSync(path.join(root, rel), 'utf8');
    const { covered, missing, exemptStale } = computeCiGateCoverage({ manifest, ciText });
    for (const id of exemptStale) console.error(`! ci-gate-parity [${rel}]: exempt gate '${id}' is not in the manifest — stale exemption, remove it from CI_EXEMPT_GATES`);
    if (missing.length) {
      failed = true;
      for (const id of missing) console.error(`✗ ci-gate-parity [${rel}]: manifest gate '${id}' is NOT enforced in this backstop — a --no-verify bypass of it would slip CI. Add a step running its script (or a run-gates.mjs <chain> step covering it), or add '${id}' to CI_EXEMPT_GATES with a documented reason.`);
    } else {
      console.log(`✓ ci-gate-parity [${rel}]: ${covered.length} manifest gate(s) enforced (${CI_EXEMPT_GATES.size} exempted).`);
    }
  }
  if (failed) { console.error(`\n✗ ci-gate-parity: a manifest gate is missing from a CI backstop (checked ${present.length} file(s)).`); return 1; }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
