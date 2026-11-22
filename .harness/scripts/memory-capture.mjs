#!/usr/bin/env node
/**
 * @description Stop/PreCompact/SessionStart memory-capture hook driver (closes the P0-5 gap:
 * memory tiers were committed in-repo but nothing distilled a live session into them, and nothing
 * reminded the agent to re-read AGENTS.md after compaction — see AGENTS.md invariant #4).
 *
 * Invoked by `.claude/settings.json` as `node "${CLAUDE_PROJECT_DIR}/.harness/scripts/memory-capture.mjs" <Event>`
 * with the Claude Code hook JSON piped on stdin (session_id, transcript_path, cwd, hook_event_name,
 * compaction_trigger|source, ...).
 *
 * - Stop / PreCompact: distill a short episodic entry (timestamp + event + brief state, best-effort
 *   excerpt from the transcript tail) and APPEND it to `.harness/memory/episodic/<YYYY-MM-DD>.md`
 *   (created on first use), then refresh the "Now" pointer in `.harness/memory/memory.md`.
 * - SessionStart: emit `hookSpecificOutput.additionalContext` on stdout. When `source === "compact"`
 *   this is the re-read-after-compaction reminder (AGENTS.md invariant #4); for other sources it's a
 *   lean pointer at the hot memory index.
 *
 * Hard requirement: NEVER crash the hook loop. Every path — malformed/empty stdin, unwritable memory
 * dir, unreadable transcript, anything — is caught and the process still exits 0. A hook that throws
 * would break the user's Claude Code session, which is strictly worse than a missed memory entry.
 */
import { existsSync, mkdirSync, appendFileSync, readFileSync, writeFileSync, openSync, fstatSync, readSync, closeSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { repoRoot as gitRoot, currentBranch, git } from './lib/repo.mjs';
import { loadConfig } from './lib/config.mjs';
import { hostFingerprints, redactHostPaths } from './lib/identity.mjs';

const EPISODIC_DIR = ['.harness', 'memory', 'episodic'];
const MEMORY_INDEX = ['.harness', 'memory', 'memory.md'];
const MEMORY_PATHSPEC = '.harness/memory';
const TRANSCRIPT_TAIL_BYTES = 8192; // best-effort tail read, bounded so a huge transcript can't stall the hook
const EXCERPT_MAX = 200;

/** Best-effort, never-throw stdin read (hooks always pipe JSON and close stdin). */
export function readStdin() {
  try {
    const data = readFileSync(0, 'utf8');
    return typeof data === 'string' ? data : '';
  } catch {
    return '';
  }
}

/** Parse the hook JSON payload; returns {} (never throws) on empty/malformed input. */
export function parseHookInput(raw) {
  if (!raw || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/** ISO 'YYYY-MM-DD' for `now`, used both for the episodic filename and entry timestamp. */
export function isoDate(now) {
  return now.toISOString().slice(0, 10);
}

/**
 * Best-effort excerpt of the most recent message text from a transcript.jsonl tail. Never throws;
 * returns null if the file is missing/unreadable/empty/unparseable within the bounded tail window.
 */
export function tailExcerpt(transcriptPath) {
  if (!transcriptPath || typeof transcriptPath !== 'string') return null;
  let fd;
  try {
    if (!existsSync(transcriptPath)) return null;
    fd = openSync(transcriptPath, 'r');
    const size = fstatSync(fd).size;
    const start = Math.max(0, size - TRANSCRIPT_TAIL_BYTES);
    const len = size - start;
    if (len <= 0) return null;
    const buf = Buffer.alloc(len);
    readSync(fd, buf, 0, len, start);
    const chunk = buf.toString('utf8');
    const lines = chunk.split('\n').filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      // The first line of the tail window may be a truncated partial JSON line — skip parse failures.
      try {
        const rec = JSON.parse(lines[i]);
        const text = extractText(rec);
        if (text) return text.slice(0, EXCERPT_MAX).replace(/\s+/g, ' ').trim();
      } catch {
        continue;
      }
    }
    return null;
  } catch {
    return null;
  } finally {
    if (fd !== undefined) { try { closeSync(fd); } catch { /* best-effort */ } }
  }
}

/** Pull a plain-text excerpt out of a transcript record shape, tolerant of schema drift. */
function extractText(rec) {
  const msg = rec?.message ?? rec;
  const content = msg?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    const textBlock = content.find((b) => b && typeof b.text === 'string');
    if (textBlock) return textBlock.text;
  }
  if (typeof rec?.summary === 'string') return rec.summary;
  return null;
}

/**
 * Pure: render one markdown episodic entry (no I/O). `fp` (host fingerprints) is injected so cwd /
 * transcript paths are collapsed to ~ / <user> BEFORE they land in the committed journal — this is the
 * write-time inverse of the identity-scan gate (a raw `/home/<user>/…` here would trip that gate on the
 * next `chore(memory)` commit). Default `{}` → no redaction (keeps existing pure-function tests stable).
 */
export function distillEntry({ event, data, now, fp = {} }) {
  const ts = now.toISOString();
  const sessionId = data.session_id || 'unknown-session';
  const clean = (v) => redactHostPaths(v, fp);
  const lines = [`### ${ts} — ${event} (session ${sessionId})`];
  if (data.cwd) lines.push(`- cwd: ${clean(data.cwd)}`);
  if (data.compaction_trigger) lines.push(`- compaction_trigger: ${data.compaction_trigger}`);
  if (data.source) lines.push(`- source: ${data.source}`);
  if (data.transcript_path) lines.push(`- transcript: ${clean(data.transcript_path)}`);
  const excerpt = data.__excerpt;
  lines.push(`- note: ${excerpt ? clean(excerpt) : 'no transcript excerpt available'}`);
  return lines.join('\n') + '\n';
}

/**
 * Pure: coalesce `entryMd` into `existingContent` keyed by `sessionId`, so one session yields ONE
 * stanza instead of one-per-turn (the Stop hook fires every turn; without this the file — and the
 * `chore(memory)` commit that follows it — churns per-turn). A stanza spans its `### ` heading
 * (as emitted by `distillEntry`, carrying `(session <id>)`) to the next `### ` or EOF.
 * - Existing stanza + `upsert:false` (Stop) → return content UNCHANGED (`changed:false`): the turn
 *   leaves the file clean, so no commit. Idempotent.
 * - Existing stanza + `upsert:true` (PreCompact) → replace it in place, preserving separators.
 * - No stanza yet, or a falsy/`unknown-session` id → append (never collapse unrelated unknowns).
 * @returns {{content:string, changed:boolean}}
 */
export function coalesceStanza(existingContent, entryMd, sessionId, opts = {}) {
  const { upsert = false } = opts;
  const content = existingContent || '';
  const canCoalesce = sessionId && sessionId !== 'unknown-session';
  // Split keeping each `### ` at the start of its piece; parts[0] is the header (pre-first-stanza).
  const parts = content.split(/(?=^### )/m);
  const marker = `(session ${sessionId})`;
  const idx = canCoalesce
    ? parts.findIndex((p) => p.startsWith('### ') && p.split('\n', 1)[0].includes(marker))
    : -1;

  if (idx === -1) {
    // Append, preserving the existing `\n`-separated stanza convention (matches appendFileSync path).
    return { content: content + `\n${entryMd}`, changed: true };
  }
  if (!upsert) return { content, changed: false }; // Stop on an already-recorded session: skip.
  // Upsert: swap the stanza body but keep the old part's trailing separator whitespace intact.
  const oldPart = parts[idx];
  const trailing = oldPart.slice(oldPart.trimEnd().length);
  parts[idx] = entryMd.replace(/\n+$/, '') + trailing;
  return { content: parts.join(''), changed: true };
}

/**
 * Append/coalesce `entryMd` into the episodic file for `now`'s date, creating dir/file as needed.
 * Legacy 3-arg call (`sessionId` omitted) keeps the pure-append behavior and returns the file PATH.
 * Session-aware call routes through `coalesceStanza` and returns `{file, changed}` (writes iff changed).
 */
export function appendEpisodic(root, entryMd, now, sessionId, opts = {}) {
  const dir = path.join(root, ...EPISODIC_DIR);
  const file = path.join(dir, `${isoDate(now)}.md`);
  const header = `# Episodic memory — ${isoDate(now)}\n\n`;

  if (!sessionId) {
    // Backward-compatible pure append (returns the path — existing callers/tests depend on this).
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    if (!existsSync(file)) writeFileSync(file, header);
    appendFileSync(file, `\n${entryMd}`);
    return file;
  }

  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const existing = existsSync(file) ? readFileSync(file, 'utf8') : header;
  const { content, changed } = coalesceStanza(existing, entryMd, sessionId, opts);
  if (changed) writeFileSync(file, content);
  return { file, changed };
}

/** Idempotently refresh the "Last captured session" pointer under the memory.md "## Now" heading. */
export function updateMemoryIndex(root, now) {
  const file = path.join(root, ...MEMORY_INDEX);
  if (!existsSync(file)) return false;
  let content = readFileSync(file, 'utf8');
  const marker = '- Last captured session:';
  const line = `${marker} ${isoDate(now)} (see \`.harness/memory/episodic/${isoDate(now)}.md\`)`;
  if (content.includes(marker)) {
    content = content.replace(new RegExp(`^${marker}.*$`, 'm'), line);
  } else if (content.includes('## Now')) {
    content = content.replace(/## Now\n/, `## Now\n${line}\n`);
  } else {
    content += `\n## Now\n${line}\n`;
  }
  writeFileSync(file, content);
  return true;
}

/**
 * Best-effort, never-throw: commit any dirty `.harness/memory` state as its own small `chore(memory)`
 * commit, scoped by pathspec so it can never sweep up unrelated staged work (verified: `git add --
 * <pathspec>` followed by `git commit -- <pathspec>` only touches that path's index/tree entries).
 *
 * Gated to the default branch — matches invariant #6's "exempt paths may commit directly to the
 * default branch" and AGENTS.md's "commit ASAP when not working in a worktree". A worktree's memory
 * copy is a separate, per-date-file working tree; auto-committing there risks a divergent
 * episodic-file history that conflicts on merge, so it's left alone on purpose.
 *
 * All git calls use stdio:'ignore' — on SessionStart this function runs before the hook writes its
 * JSON to stdout, and any git output on that stream would corrupt the hookSpecificOutput payload.
 */
export function commitMemoryIfDirty(root, config) {
  try {
    const defaultBranch = config?.defaultBranch || 'main';
    if (currentBranch() !== defaultBranch) return false;
    const status = execFileSync('git', ['status', '--porcelain', '--', MEMORY_PATHSPEC], {
      cwd: root,
      encoding: 'utf8',
    });
    if (!status.trim()) return false;
    execFileSync('git', ['add', '--', MEMORY_PATHSPEC], { cwd: root, stdio: 'ignore' });
    execFileSync(
      'git',
      ['commit', '-m', 'chore(memory): capture session state', '--', MEMORY_PATHSPEC],
      { cwd: root, stdio: 'ignore' },
    );
    return true;
  } catch {
    return false; // best-effort; a failed gate/commit must never break the hook
  }
}

/** Pure: summarize the current Git state for SessionStart context; failures fail open. */
export function gitStateSnapshot(root, gitFn = git) {
  try {
    const branch = gitFn(['branch', '--show-current'], { cwd: root });
    const status = gitFn(['status', '--short'], { cwd: root });
    const log = gitFn(['log', '--oneline', '-3'], { cwd: root });
    if (branch.code !== 0 || status.code !== 0 || log.code !== 0) return '';
    const branchName = branch.out || '(detached HEAD)';
    const changed = status.out ? status.out.split(/\r?\n/).slice(0, 40).join('\n') : '(clean)';
    const recent = log.out || '(no commits)';
    return `Git state:\n- branch: ${branchName}\n- status:\n${changed}\n- recent commits:\n${recent}`;
  } catch {
    return '';
  }
}

/** Pure: build the SessionStart additionalContext string per AGENTS.md invariant #4. */
export function buildSessionStartContext(data, root = process.cwd(), gitFn = git) {
  const snapshot = gitStateSnapshot(root, gitFn);
  if (data.source === 'compact') {
    return (
      'Context was just compacted. Per AGENTS.md invariant #4 ("After context compaction: re-read this ' +
      'file and the active plan before continuing"), re-read AGENTS.md and the active plan under ' +
      'docs/plans/ (or docs/plans/worktrees/) before taking any further action. Also skim ' +
      '.harness/memory/memory.md (hot index) and the latest .harness/memory/episodic/ entry for recent state.' +
      (snapshot ? `\n\n${snapshot}` : '')
    );
  }
  return (
    'kaizen harness session start. Hot memory index: .harness/memory/memory.md. ' +
    'If this is a resumed/compacted session, re-read AGENTS.md first (invariant #4).' +
    (snapshot ? `\n\n${snapshot}` : '')
  );
}

function safeRoot() {
  try {
    return gitRoot();
  } catch {
    return process.cwd();
  }
}

function safeConfig(root) {
  try {
    return loadConfig(root);
  } catch {
    return { defaultBranch: 'main' };
  }
}

export function main(argv) {
  try {
    const cliEvent = argv[2] || 'unknown';
    const raw = readStdin();
    const data = parseHookInput(raw);
    const event = data.hook_event_name || cliEvent;
    const root = safeRoot();
    const now = new Date();

    if (event === 'SessionStart') {
      // Sweep first: a prior session's Stop may have written memory but never got to commit it
      // (crash, kill -9, etc). This is the first chance to self-heal before any new work starts.
      commitMemoryIfDirty(root, safeConfig(root));
      const additionalContext = buildSessionStartContext(data, root);
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext },
        }) + '\n',
      );
      return 0;
    }

    // Stop / PreCompact / anything else: distill + coalesce per session, never fatal.
    // Stop fires every turn → write-once-per-session (idempotent skip). PreCompact is a rare, meaningful
    // boundary (AGENTS.md invariant #4) → upsert so the stanza reflects the latest state.
    data.__excerpt = tailExcerpt(data.transcript_path);
    const entryMd = distillEntry({ event, data, now, fp: hostFingerprints() });
    const { changed } = appendEpisodic(root, entryMd, now, data.session_id || 'unknown-session', {
      upsert: event === 'PreCompact',
    });
    // Only refresh the "Now" pointer when we actually recorded something — a skipped Stop leaves the
    // tree clean, which is the whole point (no per-turn `chore(memory)` commit).
    if (changed) {
      updateMemoryIndex(root, now);
      commitMemoryIfDirty(root, safeConfig(root));
    }
    return 0;
  } catch {
    // Fail-open by design: a broken hook must never break the Claude Code session loop.
    return 0;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv));
}
