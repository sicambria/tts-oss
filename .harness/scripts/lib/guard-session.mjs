#!/usr/bin/env node
/**
 * @description The guard-session/GUARD-ID subsystem: a session-token + call-budget + staleness guard
 * for "scaffolder commands" (`config.guard.scaffolderCommands`). Genericizes changemappers' consent-token
 * pattern for destructive/expensive operations — any command name opts in by being listed in config.
 * Pure core (state file I/O only, no process/exit calls) so it's directly unit-testable.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

/** Repo-relative path to the ephemeral session state file (already gitignored: `.harness/state/`). */
export function sessionPath(root) {
  return path.join(root, '.harness', 'state', 'guard-session.json');
}

/**
 * Read the current session, or `null` if absent/malformed. A malformed file is treated the same as
 * a missing one (fail-closed via "no session", forcing a fresh `guard start`) rather than thrown —
 * unlike config, this state is disposable, not authoritative.
 */
export function loadSession(root) {
  const p = sessionPath(root);
  if (!existsSync(p)) return null;
  try {
    const parsed = JSON.parse(readFileSync(p, 'utf8'));
    if (!parsed || typeof parsed.guardId !== 'string' || typeof parsed.mintedAt !== 'string' || typeof parsed.calls !== 'number') return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveSession(root, session) {
  const p = sessionPath(root);
  mkdirSync(path.dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(session, null, 2) + '\n');
}

/** Mint a fresh session (new GUARD-ID, calls reset to 0) and persist it. Returns the session. */
export function mintSession(root, now = Date.now()) {
  const session = { guardId: randomBytes(16).toString('hex'), mintedAt: new Date(now).toISOString(), calls: 0 };
  saveSession(root, session);
  return session;
}

/** Clear the current session (if any). */
export function resetSession(root) {
  const p = sessionPath(root);
  if (existsSync(p)) unlinkSync(p);
}

/** Is this session past its TTL (`config.guard.staleMinutes`)? */
export function isStale(session, cfg, now = Date.now()) {
  const staleMs = (cfg.guard?.staleMinutes ?? 30) * 60_000;
  return now - Date.parse(session.mintedAt) > staleMs;
}

/**
 * Guard consumers that are NOT note-scaffolders (those live in scaffold-note.mjs SCAFFOLD_COMMANDS).
 * `next:execute` — the /next phase gate calls requireGuard() before spawning executor subagents, so the
 * expensive/irreversible step opts into the session budget. This is the first non-scaffolder consumer;
 * its existence is what lets doctor's guard-check fail closed (roadmap Debt #4).
 */
export const GUARD_CONSUMERS = new Set(['next:execute']);

/**
 * The guard predicate. Commands not listed in `cfg.guard.scaffolderCommands` pass through unguarded.
 * Guarded commands require a live, non-stale session under budget; a passing call consumes one unit
 * of the session's call budget.
 * @returns {{ok: boolean, guarded: boolean, reason?: string, session?: object}}
 */
export function requireGuard(root, cfg, commandName, now = Date.now()) {
  const guardedCommands = cfg.guard?.scaffolderCommands || [];
  if (!guardedCommands.includes(commandName)) return { ok: true, guarded: false };

  const session = loadSession(root);
  if (!session) return { ok: false, guarded: true, reason: `no active guard session for '${commandName}' — run \`kaizen guard start\`` };
  if (isStale(session, cfg, now)) {
    return { ok: false, guarded: true, reason: `guard session stale (>${cfg.guard?.staleMinutes ?? 30}m) — run \`kaizen guard start\`` };
  }
  const maxCalls = cfg.guard?.maxCalls ?? 40;
  if (session.calls >= maxCalls) {
    return { ok: false, guarded: true, reason: `guard session call budget exhausted (${maxCalls}) — run \`kaizen guard start\`` };
  }

  const updated = { ...session, calls: session.calls + 1 };
  saveSession(root, updated);
  return { ok: true, guarded: true, session: updated };
}

/** Session status for `guard status` / `doctor` — never throws, always returns a summary. */
export function guardStatus(root, cfg, now = Date.now()) {
  const session = loadSession(root);
  if (!session) return { active: false, stale: false, guardId: null, callsUsed: 0, callsRemaining: cfg.guard?.maxCalls ?? 40 };
  const stale = isStale(session, cfg, now);
  const maxCalls = cfg.guard?.maxCalls ?? 40;
  return {
    active: !stale,
    stale,
    guardId: session.guardId,
    callsUsed: session.calls,
    callsRemaining: Math.max(0, maxCalls - session.calls),
    mintedAt: session.mintedAt,
  };
}
