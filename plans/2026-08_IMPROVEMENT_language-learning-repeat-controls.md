# Plan: Default-off repetition controls

**Type:** Improvement plan
**Date:** 2026-08-02
**Status:** Implemented and verified
**Branch:** `improvement/language-learning-repeat-off`

## Summary

Make language-learning target repetition opt-in by default and add an opt-in
sentence-repetition checkbox to the Document to Audio Converter. Keep the
existing chunking, pause, and engine-selection behavior when repetition is off.

## Implementation steps

1. Change language-learning defaults and session fallbacks from `True` to
   `False`, preserving the existing wizard checkbox and persisted setting.
2. Add a converter-level `Repeat each sentence` option to the conversion run
   and UI. When enabled, split extracted text into sentence-sized synthesis
   units and append each unit's audio twice with the normal pause between
   occurrences.
3. Add regression tests for default settings, language-practice request
   sequences, converter run capture, and repeated converter assembly.
4. Update README usage notes and run focused tests, Ruff, compile, and diff
   checks.

## Verification results

- GREEN: Python 3.11 focused suite — 121 passed across settings, language
  practice, wizard, converter, and chunking tests.
- GREEN: `ruff check app.py tests/`.
- GREEN: `python3.11 -m py_compile` for the changed module and tests.
- GREEN: `git diff --check`.
- The repository worktree had no `.venv`; checks used a temporary dependency
  target because the host's default Python 3.14 is outside the project's
  supported 3.9–3.11 range.

## Verification evidence

- Default language-learning setting: `app.py:258-274`.
- Language-learning request construction: `app.py:5810-5854`.
- Document converter UI and run capture: `app.py:2919-3033`, `app.py:3390-3399`.
- Document synthesis assembly: `app.py:3754-3819`.
- Existing test coverage patterns: `tests/test_language_practice_integration.py:103-154`, `tests/test_wizard_logic.py:521-559`.

## Risks and rollback

The change is limited to repetition controls. The default-off path retains the
current synthesis flow, and the feature can be rolled back by reverting the
single commit.
