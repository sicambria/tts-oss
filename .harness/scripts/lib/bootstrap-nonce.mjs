#!/usr/bin/env node
/**
 * @description Single-use bootstrap-nonce authorization — the ONE source of truth for "is this the
 * sanctioned `kaizen init` install commit?" used by all three gate sites (pre-commit branch-guard,
 * chained-hooks skip, decision-log override audit).
 *
 * Threat closed: a bare `process.env.KZ_BOOTSTRAP === '1'` was an UNAUTHENTICATED, REPLAY-ABLE bypass —
 * any actor with env access could set `KZ_BOOTSTRAP=1` to skip the override audit, the branch guard, and
 * chained prior hooks, defeating the "overrides are audited, never silent" invariant. Instead, the
 * installer writes a RANDOM single-use nonce to the gitignored `.harness/state/` dir and sets
 * `KZ_BOOTSTRAP=<nonce>` for exactly that one commit; each gate authorizes ONLY when the env value equals
 * the on-disk nonce. The installer deletes the nonce in a `finally` (success AND failure), so the replay
 * window closes with the install: afterward, `KZ_BOOTSTRAP` set to anything finds no matching nonce → rejected.
 *
 * The property is NO-REPLAY, not unforgeability-against-a-local-actor: a random single-use token consumed
 * by the installer, not a signed credential. Validity is scoped to the one install commit (whose chained
 * gates each read the nonce in separate subprocesses — so the nonce is checked, NOT consumed, on read).
 *
 * TTL scoping (HARDEN-7 / wargame WI-8): the installer clears the nonce in a `finally`, which a SIGKILL /
 * power-loss SKIPS — leaving a nonce that would otherwise authorize INDEFINITELY (a local actor could read
 * the gitignored file and replay it). To slam that residual window, the nonce carries a creation timestamp
 * and `bootstrapAuthorized` additionally requires the nonce to be WITHIN the TTL (now − createdAt ≤ TTL).
 * The default is 5 minutes: comfortably longer than a real install (seconds — the chained gates read the
 * nonce in subprocesses within that one commit) yet short enough that a stale leftover is inert. This is
 * defense-in-depth ON TOP OF single-use: even the descoped hard-kill case now self-heals after the TTL.
 *
 * Defensive by contract: a missing / empty / malformed / legacy-bare / mismatched / EXPIRED nonce →
 * `bootstrapAuthorized` returns `false` (not authorized). It never throws.
 */
import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';

// Gitignored (see .gitignore `.harness/state/`) so the nonce is NEVER staged into the bootstrap commit.
const NONCE_REL = path.join('.harness', 'state', 'bootstrap-nonce');

/**
 * Bootstrap-nonce time-to-live (ms). A nonce older than this is treated as an inert leftover from an
 * abnormally-terminated install (see WI-8) and no longer authorizes. 5 min ≫ a real install (seconds)
 * but short enough to close the residual replay window.
 */
export const NONCE_TTL_MS = 300_000;

/** Absolute path to the nonce file for a given repo root. */
function noncePath(root) {
  return path.join(root, NONCE_REL);
}

/**
 * Parse a nonce file's raw contents into `{ nonce, createdAt }`, or `null` for anything that is not a
 * well-formed current-format record (malformed JSON, a legacy bare-nonce string, a missing field, a
 * non-finite timestamp). Fail-closed by construction — the caller treats `null` as "not authorized".
 * @param {string} raw file contents
 * @returns {{nonce: string, createdAt: number}|null}
 */
function parseNonceRecord(raw) {
  let obj;
  try {
    obj = JSON.parse(raw);
  } catch {
    return null; // legacy bare-nonce file, or corrupt JSON → fail closed (never crash)
  }
  if (!obj || typeof obj !== 'object') return null;
  const nonce = typeof obj.nonce === 'string' ? obj.nonce.trim() : '';
  if (nonce.length === 0) return null;
  if (!Number.isFinite(obj.createdAt)) return null;
  return { nonce, createdAt: obj.createdAt };
}

/**
 * Read + parse the on-disk nonce record. Returns `{ nonce, createdAt }` or `null` for a
 * missing/empty/malformed/legacy-bare file. Never throws.
 * @param {string} root repo root
 * @returns {{nonce: string, createdAt: number}|null}
 */
export function readNonceRecord(root) {
  let raw;
  try {
    raw = readFileSync(noncePath(root), 'utf8');
  } catch {
    return null; // no nonce on disk → the install window is closed
  }
  return parseNonceRecord(raw);
}

/**
 * Is the current process authorized as the sanctioned bootstrap install commit?
 * True iff `process.env.KZ_BOOTSTRAP` is non-empty AND equals the on-disk nonce AND that nonce is within
 * the TTL. Never throws; any missing/empty/malformed/legacy-bare/mismatched/EXPIRED nonce (or unreadable
 * root) → false.
 * @param {string} root repo root
 * @returns {boolean}
 */
export function bootstrapAuthorized(root) {
  const env = process.env.KZ_BOOTSTRAP;
  if (typeof env !== 'string' || env.trim().length === 0) return false;
  const rec = readNonceRecord(root);
  if (rec === null) return false; // no/malformed/legacy nonce → a bare env var is a rejected replay
  if (Date.now() - rec.createdAt > NONCE_TTL_MS) return false; // expired → residual window slammed
  return env.trim() === rec.nonce;
}

/**
 * Is there a STALE (expired or legacy/malformed) leftover nonce on disk? For `doctor` — a nonce older
 * than the TTL (or in the pre-TTL bare format) can no longer authorize any install (`bootstrapAuthorized`
 * already rejects it), so it is inert residue from an abnormally-terminated install, not an active
 * bypass. A fresh within-TTL nonce (present only mid-install) → `false`. A missing file → `false`. Never
 * throws.
 * @param {string} root repo root
 * @returns {boolean}
 */
export function isNonceStale(root) {
  let raw;
  try {
    raw = readFileSync(noncePath(root), 'utf8');
  } catch {
    return false; // no file → nothing to flag
  }
  const rec = parseNonceRecord(raw);
  if (rec === null) return true; // present but legacy/malformed → inert leftover
  return Date.now() - rec.createdAt > NONCE_TTL_MS;
}

/**
 * Generate a fresh random nonce, persist it (with its creation timestamp) to the gitignored state dir,
 * and return the bare nonce string. The installer sets `KZ_BOOTSTRAP` to this value for the single
 * sanctioned commit; the return contract is unchanged so `cli/commands/init.mjs` needs no edit.
 * @param {string} root repo root
 * @returns {string} the nonce
 */
export function writeBootstrapNonce(root) {
  const nonce = randomBytes(16).toString('hex');
  const p = noncePath(root);
  mkdirSync(path.dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify({ nonce, createdAt: Date.now() }), { mode: 0o600 });
  return nonce;
}

/**
 * Delete the nonce file — closes the replay window. Called by the installer in a `finally` (on BOTH
 * commit success and failure). Never throws (a missing file is fine).
 * @param {string} root repo root
 */
export function clearBootstrapNonce(root) {
  try {
    rmSync(noncePath(root), { force: true });
  } catch {
    /* never throw: the window also closes if the state dir is otherwise removed */
  }
}
