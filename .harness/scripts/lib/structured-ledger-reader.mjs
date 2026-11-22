/**
 * @description Read-only derived index over allowlisted committed memory/incident metadata.
 * Report-only first cut: parses `Key: value` frontmatter from an allowlist of existing files,
 * builds a deterministic index, and NEVER mutates sources. Rebuild is pure (inputs → index).
 *
 * Schema allowlist (metadata ONLY — prompts, credentials, PII, and transcripts are excluded
 * by construction: anything outside ALLOWED_KEYS is dropped, never indexed):
 *   id, title, date, type, area, status
 * Excluded dirs (never traversed): node_modules, .git, transcripts/, secrets/, archive/private/.
 */

export const ALLOWED_KEYS = new Set(['id', 'title', 'date', 'type', 'area', 'status']);

export const EXCLUDED_DIRS = new Set(['node_modules', '.git', 'transcripts', 'secrets', 'private']);

export const ALLOWED_TYPES = new Set(['incident', 'reference']);
export const ALLOWED_STATUSES = new Set(['active', 'monitoring', 'resolved']);

/**
 * Parse `Key: value` frontmatter from the head of `text`. Returns
 * { data, malformed } where data holds only ALLOWED_KEYS entries.
 * Lines before the first blank line that lack a colon mark the block malformed
 * (the entry is still returned with what parsed — caller decides disposition).
 */
export function parseFrontmatter(text) {
  const data = {};
  let malformed = null;
  const lines = String(text ?? '').split('\n');
  for (const ln of lines) {
    if (ln.trim() === '') break;
    const i = ln.indexOf(':');
    if (i < 0) { malformed = `non-frontmatter line: ${ln.slice(0, 60)}`; break; }
    const key = ln.slice(0, i).trim().toLowerCase();
    const value = ln.slice(i + 1).trim();
    if (ALLOWED_KEYS.has(key) && value) data[key] = value;
    // Disallowed keys (prompt, credentials, transcript, author-email, …) are dropped silently.
  }
  return { data, malformed };
}

/** True iff `rel` (POSIX) lives under an excluded directory. */
export function isExcluded(rel) {
  return String(rel).split('/').some((seg) => EXCLUDED_DIRS.has(seg));
}

/**
 * Build a deterministic index from parsed entries.
 * @param {Array<{rel:string, data:object, malformed:string|null}>} entries
 * @returns {{ index:Array, duplicates:Array<string>, skipped:Array }}
 * Stable ordering: sort by (date, id, rel). Duplicate ids are reported, first wins.
 */
export function buildIndex(entries) {
  const sorted = [...entries].sort((a, b) =>
    String(a.data.date ?? '').localeCompare(String(b.data.date ?? '')) ||
    String(a.data.id ?? '').localeCompare(String(b.data.id ?? '')) ||
    String(a.rel ?? '').localeCompare(String(b.rel ?? '')));
  const seen = new Set();
  const index = [];
  const duplicates = [];
  const skipped = [];
  for (const e of sorted) {
    if (e.malformed) { skipped.push({ rel: e.rel, why: e.malformed }); continue; }
    if (!e.data.id) { skipped.push({ rel: e.rel, why: 'missing id' }); continue; }
    if (seen.has(e.data.id)) { duplicates.push(e.data.id); continue; }
    seen.add(e.data.id);
    index.push({ rel: e.rel, ...e.data });
  }
  return { index, duplicates, skipped };
}

/**
 * Pure rebuild over an in-memory file map: { relPath: content }.
 * Applies the allowlist + excluded-dir filter, then builds the index.
 * Never touches the filesystem — callers supply already-read committed files.
 */
export function rebuildIndex(fileMap) {
  const entries = [];
  for (const [rel, content] of Object.entries(fileMap)) {
    if (isExcluded(rel)) continue;
    const { data, malformed } = parseFrontmatter(content);
    entries.push({ rel, data, malformed });
  }
  return buildIndex(entries);
}
