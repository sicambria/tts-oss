# Plan: Place voice preview in the Options action column

**Type:** Bug fix
**Date:** 2026-11-01
**Status:** Implemented
**Branch:** `improvement/tts-preview-question-column`

## Summary

Move the compact voice preview button out of the voice selector frame and into
the Options panel's third column, aligned with the Engine help button. Allow the
voice selector to use the full expandable second column.

## Implementation steps

1. Move the preview button to Options column 2, row 2, and size it to align with
   the existing help button.
2. Keep the voice selector in the full-width expandable column and retain the
   existing preview/stop behavior and tooltip.
3. Inspect the diff and verify Python syntax and whitespace without running the
   test suite.

## Verification results

Pending.

## Risks and rollback

This only changes the Options panel layout. Revert this change to restore the
previous preview button placement.
