/**
 * @description One-work-package red/green evidence pilot validator (review evidence, NOT proof).
 * Before implementation the agent captures { testName, testCmd, redHash, redExit };
 * after implementation it runs the SAME named test and records { greenExit }.
 * This module only validates that an evidence record is internally consistent and
 * reviewable — it cannot prove a historical red state (hashes are forgeable), so it
 * must never back a universal pre-commit hook. Existing test-gaming + verify gates
 * remain the backstop.
 *
 * Record shape:
 * { testName, testCmdBefore, testCmdAfter, redHash, redExit, greenExit, docsOnly? }
 */

function shaLike(s) {
  return typeof s === 'string' && /^[0-9a-f]{8,64}$/i.test(s);
}

/**
 * Validate one pilot evidence record.
 * @returns {{ ok:boolean, errors:string[], advisory:string[] }}
 */
export function validateTddEvidence(rec = {}) {
  const errors = [];
  const advisory = [];
  if (rec.docsOnly === true) {
    return { ok: true, errors, advisory: ['docs-only change — red/green evidence exempt'] };
  }
  if (!rec.testName || !String(rec.testName).trim()) errors.push('absent test identity: testName required');
  if (!rec.testCmdBefore) errors.push('absent test command: testCmdBefore required');
  if (!rec.redHash) {
    errors.push('absent red proof: redHash required (capture failing-test output hash before implementing)');
  } else if (!shaLike(rec.redHash)) {
    errors.push('malformed redHash: expected hex digest (8–64 chars)');
  }
  if (rec.testCmdBefore && rec.testCmdAfter && rec.testCmdBefore !== rec.testCmdAfter) {
    errors.push(`mismatched identity: test command changed between red and green (${rec.testCmdBefore} → ${rec.testCmdAfter})`);
  }
  if (rec.testNameBefore && rec.testName && rec.testNameBefore !== rec.testName) {
    errors.push(`mismatched identity: test name changed between red and green (${rec.testNameBefore} → ${rec.testName})`);
  }
  if (rec.greenExit !== 0) errors.push(`non-zero final run: greenExit=${rec.greenExit} (expected 0)`);
  if (Number(rec.redExit) === 0) {
    advisory.push('red run exited 0 — the "failing first" evidence is weak; reviewer should confirm the test actually exercised the change');
  }
  advisory.push('review evidence only — not cryptographic proof of historical red state; verify + test-gaming gates remain the backstop');
  return { ok: errors.length === 0, errors, advisory };
}

/** True iff the record describes a docs-only change exempt from red/green evidence. */
export function isDocsOnlyChange(files = []) {
  return files.length > 0 && files.every((f) => /\.md$/i.test(f) || /^\.harness\/(archive|memory)\//.test(f) || /^docs\//.test(f));
}
