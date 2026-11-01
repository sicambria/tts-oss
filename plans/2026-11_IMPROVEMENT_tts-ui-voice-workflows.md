# Plan: Improve TTS UI and voice workflows

**Type:** Improvement plan
**Date:** 2026-11-01
**Status:** Implemented and verified
**Branch:** `improvement/tts-ui-voice-workflows`

## Summary

Improve generation and voice-selection workflows in the Tkinter app: make
generation cancellable, add short built-in voice previews in the main Options
panel and document converter, choose a supported system locale when no language
preference is saved, and put converter document actions above the list with
icons and readable labels.

## Implementation steps

1. Resolve the system locale to an app language only when the saved settings do
   not contain an explicit `general.default_language`; use English for
   unsupported locales and preserve explicit settings.
2. Add one cancellable generation event shared by standard and language-practice
   generation. Check it at chunk boundaries and before export; present cancelled
   status in the modal and restore the main Generate button.
3. Add a short per-language phrase preview using the active engine, language,
   voice, and speed. Reuse one stoppable preview worker for the main Options
   panel and converter; clean up its temporary playback file.
4. Move converter document actions above the list and add semantic icons while
   retaining button text.
5. Add focused regression tests for locale precedence/fallback, generation
   cancellation and no export, preview request/playback cleanup, and converter
   action placement/icon configuration where headless Tk tests support it.
6. Run the focused and full available test suite, Ruff, Python compilation, and
   `git diff --check`; record results here.

## Verification results

- Locale behavior is covered for supported regional locale normalization,
  unsupported locale fallback to English, and a saved language taking priority.
- Standard generation cancellation is covered at a chunk boundary; the test
  confirms no export is called and the modal receives a cancelled result.
- Main-window voice preview is covered for selected language, engine, and voice;
  the worker test confirms it exports only to a temporary WAV and removes it
  after playback.
- GREEN: Python 3.11 compilation for `app.py` and changed tests.
- GREEN: `ruff check app.py tests`.
- GREEN: full pytest suite — 514 passed.
- GREEN: `git diff --check`.
- Visual interaction with the desktop windows was not exercised in this
  terminal session; the UI layout and callbacks were reviewed in code.

## Risks and rollback

Cancellation takes effect after an in-flight engine call returns. Voice preview
creates a temporary WAV solely for playback and removes it afterward; it does
not write to the selected output path. The changes are localized to settings
normalization, generation orchestration, the two voice selector panels, and
their tests. Revert the feature commit to roll back.
