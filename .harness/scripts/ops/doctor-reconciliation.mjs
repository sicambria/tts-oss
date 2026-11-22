/**
 * @description Evidence-first health reconciliation over captured `doctor` output.
 * Report-only: classifies each doctor signal as missing-control vs env-limit vs
 * intentional-advisory and emits a status/evidence/disposition table.
 *
 * Wave 1 scope: NO child plans, NO hook/verify/CI changes, NO new dependency.
 * Never disables a control to obtain green — a missing control stays FAIL until
 * a real fix lands; this module only reports.
 */

export const DISPOSITIONS = ['missing-control', 'env-limit', 'intentional-advisory'];

const ENV_LIMIT_RE = /not found on PATH|not installed|Windows|Git-Bash|WSL|POSIX `sh`|offline|network/i;
const ADVISORY_RE = /fresh install|not yet committed|bootstrap|created on first|branch protection|can't be verified locally|stale bootstrap nonce|version stamp|adopter/i;

/**
 * Classify one doctor line.
 * @returns {'missing-control'|'env-limit'|'intentional-advisory'}
 */
export function classifySignal(line) {
  if (ADVISORY_RE.test(line)) return 'intentional-advisory';
  if (ENV_LIMIT_RE.test(line)) return 'env-limit';
  return 'missing-control';
}

/**
 * Reconcile captured doctor output into a disposition table.
 * @param {{fails:string[], warns:string[], oks:string[]}} doctor
 * @returns {{ rows:Array<{status:string, signal:string, evidence:string, disposition:string}>, summary:object }}
 */
export function reconcileDoctor(doctor = {}) {
  const { fails = [], warns = [], oks = [] } = doctor;
  const rows = [];
  for (const signal of fails) {
    rows.push({ status: 'FAIL', signal, evidence: 'doctor FAIL line (captured output)', disposition: classifySignal(signal) });
  }
  for (const signal of warns) {
    const d = classifySignal(signal);
    rows.push({ status: 'WARN', signal, evidence: 'doctor WARN line (captured output)', disposition: d === 'missing-control' ? 'intentional-advisory' : d });
  }
  for (const signal of oks) {
    rows.push({ status: 'OK', signal, evidence: 'doctor OK line (captured output)', disposition: 'intentional-advisory' });
  }
  const summary = {
    fail: fails.length,
    warn: warns.length,
    ok: oks.length,
    missingControl: rows.filter((r) => r.disposition === 'missing-control').length,
  };
  return { rows, summary };
}

/** Render the reconciliation as a markdown status/evidence/disposition table. */
export function formatTable(reconciliation) {
  const head = '| status | signal | evidence | disposition |\n|---|---|---|---|';
  const body = reconciliation.rows.map((r) =>
    `| ${r.status} | ${r.signal.replaceAll('|', '/')} | ${r.evidence} | ${r.disposition} |`);
  return [head, ...body].join('\n');
}
