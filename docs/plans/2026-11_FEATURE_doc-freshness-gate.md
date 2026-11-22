# FEATURE: doc-freshness gate (AGENTS.md / CLAUDE.md auto-checked at commit)

**Type:** FEATURE
**Date:** 2026-11-22
**Branch:** `kaizen/doc-freshness-gate`
**Status:** Planned

## Problem

`AGENTS.md` / `CLAUDE.md` rotted silently: "no module split, no test suite"
survived the `dubbing/` package, 571 tests, and four new wizards/services.
Manual audits catch this only when someone asks. Architecture docs must be
machine-checked on the commit path, like ruff and coverage already are.

## Design

New stdlib-only checker `scripts/check_doc_freshness.py` with a pure
`check(root) -> list[str]` core, wired as the first step of
`.githooks/pre-commit` (which kaizen chains fail-closed, so the gate inherits
no-bypass enforcement without touching harness templates):

1. **Service/wizard roster:** every class defined in `app.py` matching
   `(Service|Wizard|Dialog|Coordinator)$` or in `{App, AudioPlayer,
   TextChunk}`, plus `DubbingWizard` in `dubbing/ui_wizard.py`, must be named
   in `AGENTS.md` or `CLAUDE.md`. Internal helpers (`TextChunk` aside) and
   error types are deliberately out of scope.
2. **Package layout:** every root-level dir containing `__init__.py`
   (`dubbing/`, `tests/`) must be named in `AGENTS.md`.
3. Failure prints `DOC DRIFT: <what> — update the docs`, exit 1.

Companion `tests/test_doc_freshness.py` covers the core with `tmp_path`
fixtures (clean tree passes; missing class fails; missing package fails), so
the gate itself is tested and coverage-neutral.

Also: drop the volatile "27 files" count from `AGENTS.md` (counts rot; the
gate checks structure, not numbers) and document the gate in one
supplement bullet.

## Test plan

- `scripts/check_doc_freshness.py` passes on the working tree.
- `pytest tests/test_doc_freshness.py` green (3+ cases).
- Negative control: temporarily rename a roster mention out of a scratch copy
  (never the real docs) and confirm exit 1 with the offending name.
- Full `pytest`, `ruff check app.py tests/`, `git diff --check`,
  `kaizen init --check`, `kaizen doctor` green before merge.

## Risks and rollback

- False positive blocks commits: mitigated by narrow roster rule + explicit
  failure message; rollback is `git revert` of the two hook/script commits.
- Coverage: new script is covered by its own test file; `tests/` is already
  coverage-omitted, the script is not, so the pre-push ≥85 gate still holds.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: gate ships with its own failing-first tests in tests/test_doc_freshness.py:1 and runs inside the existing chained hook at .githooks/pre-commit:6.
- [x] Reused patterns / grounding: reuses the repo's hook-chaining pattern (kaizen chains .githooks, verified at .harness/config.json:1) and the TextChunk offset contract the docs describe at app.py:740; no new infrastructure.
- [x] Security: N/A — no secrets, credentials, network, or user input; stdlib-only file reads, and the staged-diff secret scan is untouched.
