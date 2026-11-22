# Decision records — the audit trail for overrides

This directory is the concrete mechanism behind `AGENTS.md`'s **"Overrides are audited, never
silent"** invariant. Every gate override, scope cut, or non-obvious architectural call gets a dated
record here — written by the `/decide` skill (`.claude/skills/decide/SKILL.md`) and **enforced** by
the `decision-log` gate (`.harness/scripts/audits/verify-decision-log.mjs`).

This dir is `branchGuard.exemptPaths`-exempt (`^\.harness/archive/` in `.harness/config.json`), so a
record commits directly on the default branch per `AGENTS.md` invariant #6a.

## The gate: what trips it

`verify-decision-log.mjs` scans the **staged** commit. If ANY override signal is present and **no**
new/modified decision record (`*.md` here, excluding `README.md`/`TEMPLATE.md`/`_`-prefixed) is in
the same commit, the commit is **blocked**. The signals, kept tight to avoid false positives:

| # | Signal | Where it's detected |
|---|--------|---------------------|
| a | A gate id removed from a chain | a `-` line in a `*.gates.json` file (reorder-safe) |
| b | A bypass/skip key set | an added line in a config/script file (`.json`/`.mjs`/…, **not** `.md` or `test/`): secret scanner set to `none`, an `allow-fail`/`lenient`/`skip`/`bypass` flag set true, or a gate `enabled` set false |
| c | The override marker | an added line of any non-`test/` file containing the marker `KAIZEN-OVERRIDE:` (inline-code-span references like this one are ignored) |

Override signal + a decision record in the same commit → **pass**. No signal → **pass**.

## How to clear the gate

Run `/decide` (or copy `TEMPLATE.md`) to write a record, `git add` it alongside your override, and
commit. The record is the audit trail; the gate only checks it exists.

## Scope notes

- Bypass-key signals (a/b) are scoped to config/gate/script files — docs and test fixtures
  legitimately contain the literal strings, so they are excluded.
- The **commit message** channel is intentionally not read: git prepares the message *after*
  `pre-commit` runs, so a live read would be stale. Enforcement is staged-file-only. See
  `.harness/archive/decisions/2026-07-02-decision-log-pre-commit-scope.md`.

## Naming

`<YYYY-MM-DD>-<kebab-slug>.md` — e.g. `2026-07-02-drop-e2e-gate-for-hotfix.md`.
