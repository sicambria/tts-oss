# Plan: Remember the Piper default voice per language

**Type:** Improvement
**Date:** 2026-11-01
**Status:** Implemented and verified
**Branch:** `improvement/tts-per-language-voice-defaults`

## Summary

Make the Piper voice selected in the main Options panel the saved default for
the current language. Restore each language's saved voice when the user changes
languages, while retaining compatibility with the existing single default
setting and Voice Wizard.

## Implementation steps

1. Normalize a per-language Piper voice preference map in settings and preserve
   the legacy global preference for migration and compatibility.
2. Save Options voice selections under the current language and restore the
   matching preference when switching languages.
3. Ensure the document converter starts with the saved default for its chosen
   language and the Voice Wizard updates the preference for the voice's language.
4. Add tests for normalization, selection persistence, language switching, and
   settings round trips; run the full test suite, Ruff, compilation, and diff
   checks.

## Verification results

- `python -m py_compile app.py tests/test_settings.py tests/test_app_logic.py` passed.
- Ruff passed for `app.py`, `tests/test_settings.py`, and `tests/test_app_logic.py`.
- Focused settings, app logic, wizard, and Piper wizard tests passed: 210 tests.
- Full test suite passed: 520 tests.
- `git diff --check` passed.

## Risks and rollback

Existing `default_piper_voice_label` settings remain supported. The new mapping
is additive and can be removed by reverting this change.
