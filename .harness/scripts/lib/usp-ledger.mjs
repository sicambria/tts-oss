/**
 * @description Classified local claim ledger: measured / mechanism / unmeasured / limitation.
 * One classified claim per bullet; measured claims REQUIRE local `path:line` grounding
 * that resolves against the working tree. Cited evidence is hashed so drift can be
 * detected — drift is ADVISORY (requests review, never rewrites prose).
 * Parser success proves grounding, never marketing truth or causal efficacy.
 */

import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

export const CLASSES = ['measured', 'mechanism', 'unmeasured', 'limitation'];

const CITATION = /`([^`\s]+):(\d+)`/;
const CLASS_TAG = /\[(measured|mechanism|unmeasured|limitation)\]/i;

/** sha256 hex of a string (evidence fingerprint). */
export function hashEvidence(text) {
  return createHash('sha256').update(String(text)).digest('hex');
}

/** Does `rel:line` resolve under `root` (file exists AND has >= line lines)? */
export function citationResolves(root, rel, line) {
  const abs = path.resolve(root, rel);
  if (!abs.startsWith(path.resolve(root))) return false;
  try {
    return readFileSync(abs, 'utf8').split('\n').length >= Number(line);
  } catch { return false; }
}

/**
 * Validate one claim bullet.
 * @param {string} bullet raw bullet text
 * @param {string} root repo root for citation resolution
 * @returns {{ ok:boolean, errors:string[], advisory:string[], claimClass:string|null, hash:string|null }}
 */
export function checkClaim(bullet, root = process.cwd()) {
  const errors = [];
  const advisory = [];
  const tag = bullet.match(CLASS_TAG);
  const claimClass = tag ? tag[1].toLowerCase() : null;
  if (!claimClass) {
    return { ok: false, errors: ['unclassified claim: add one of [measured]/[mechanism]/[unmeasured]/[limitation]'], advisory, claimClass, hash: null };
  }
  const cite = bullet.match(CITATION);
  if (claimClass === 'measured') {
    if (!cite) {
      errors.push('uncited measured claim fails: a [measured] claim requires a resolving `path:line` citation');
    } else if (!citationResolves(root, cite[1], cite[2])) {
      errors.push(`ungrounded citation \`${cite[1]}:${cite[2]}\` — file missing or line out of range`);
    }
  }
  if (claimClass === 'limitation') {
    advisory.push('limitation recorded — the honest boundary; passes without citation');
  }
  let hash = null;
  if (cite && citationResolves(root, cite[1], cite[2])) {
    try { hash = hashEvidence(readFileSync(path.resolve(root, cite[1]), 'utf8')); }
    catch { hash = null; }
  }
  // Drift check: a pinned `sha256:<hex>` that no longer matches is advisory review, never a rewrite.
  const pin = bullet.match(/sha256:([0-9a-f]{8,64})/i);
  if (pin && hash && !hash.startsWith(pin[1].toLowerCase())) {
    advisory.push(`evidence drift: pinned sha256:${pin[1]} no longer matches — re-review the claim (advisory, never auto-rewrite)`);
  }
  return { ok: errors.length === 0, errors, advisory, claimClass, hash };
}

/**
 * Validate a ledger document (one `- ` bullet per claim).
 * @returns {{ results:Array, errors:Array<string>, advisory:Array<string> }}
 */
export function checkLedger(content, root = process.cwd()) {
  const bullets = String(content).split('\n').filter((ln) => /^- /.test(ln));
  const results = bullets.map((b) => ({ bullet: b, ...checkClaim(b, root) }));
  return {
    results,
    errors: results.flatMap((r) => r.errors),
    advisory: results.flatMap((r) => r.advisory),
  };
}
