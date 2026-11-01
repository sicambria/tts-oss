# Plan: Compact the voice preview control

**Type:** Bug fix
**Date:** 2026-11-01
**Status:** Implemented and verified
**Branch:** `fix/tts-voice-preview-layout`

## Summary

Reduce the preview control beside the voice selector to a small icon-only button
so the selected voice dropdown remains visible in the main Options panel and
document converter.

## Implementation steps

1. Remove the preview button text and use compact padding and width in both
   voice selector panels; retain an explanatory tooltip.
2. Keep the preview/stop icons as the only changing visual state so the control
   does not expand while a preview is playing.
3. Run the focused UI workflow suite, Ruff, compilation, and whitespace checks.

## Verification results

- Both voice-preview buttons are icon-only, fixed-width compact rectangles. The
  controls keep the selected voice dropdown's row space and retain a tooltip.
- GREEN: Python compilation and `ruff check app.py tests`.
- GREEN: full pytest suite — 514 passed.
- GREEN: `git diff --check`.

## Risks and rollback

The change only affects preview button sizing and label presentation. Revert the
feature commit to restore the prior controls.
