# RCA: page range lost at document-conversion start

**Date:** 2026-08-01  
**Status:** Implemented and verified

## Trigger

A conversion requested for pages 61–70 synthesized the full document (148 chunks).

## Root cause

`DocumentToAudioWizard._do_extraction` ran on the background worker and re-read Tkinter page variables there. Tkinter variables are UI-thread state, so the worker could observe an empty or stale range and default to page 1.

## Fix and prevention

The Start action now captures an immutable conversion-run snapshot on the UI thread and passes it to the worker. The worker uses that snapshot for page range, format, chapter, engine, voice, quality, and speed choices. Non-PDF page ranges render the input to a temporary PDF first: LibreOffice for DOCX/ODT and Calibre for EPUB/MOBI.

`tests/test_wizard_logic.py` asserts that a captured 61–70 range is passed to extraction. Live validation used the untracked `book-sample.odt`: LibreOffice rendered 228 pages and the 61, 61–62, and 61–70 ranges produced distinct text fingerprints.

## Rollback

Revert the corrective commit. No source document or rendered PDF is persisted by the conversion path.
