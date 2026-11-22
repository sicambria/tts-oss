# RCA: sparse duplicated words or sentences in chapter audio

**Type:** RCA and corrective change
**Date:** 2026-08-01
**Branch:** `fix/xtts-boundary-duplication`
**Status:** Implemented and verified

## User report and scope

The symptom is a few duplicated words or sentences per generated chapter, not the deterministic target-repeat cadence in the language-learning workflow. This change covers normal editor and document-wizard synthesis for XTTS, Piper, and Pocket, which all use the same production text chunker. It does not tune model sampling or alter document source extraction.

The immediately preceding language-learning default change is unrelated to this report. It will be fully reverted in the same corrective change: language-learning retains its documented repeat-by-default behaviour and its opt-out checkbox.

## Evidence-backed RCA

### What was ruled out

- **[VF] Source-span duplication:** `chunk_text_with_offsets` (`app.py:579-614`) creates each current chunk from one contiguous, non-overlapping range. A representative 670-character chapter probe reconstructed every source word exactly once across 3 chunks; its spans were `0-272`, `273-548`, and `549-670`.
- **[VF] Application assembly duplication:** each engine appends every yielded segment once (`app.py:1673-1684`, `1744-1755`, `1885-1895`); the document-wizard and main generation consumers do the same (`app.py:3047-3055`, `5511-5548`). Between-chunk output is silence only.
- **[VF] Language-learning request duplication:** its duplicate target requests occur only under an explicit practice-session flag and cannot explain a few occurrences in a normal chapter. The prior default-setting change is therefore a false lead for this incident.

### Confirmed defect

- **[VF] The sentence-aware chunker exists but is dead for production synthesis.** `chunk_text` (`app.py:542-559`) prefers sentence and clause boundaries, but XTTS, Piper, and Pocket all instead call the word-only `chunk_text_with_offsets`.
- **[VF] The active offset chunker creates arbitrary mid-sentence fragments.** In the chapter probe above, both transitions were inside sentences: `"The fourth unique | sentence describes …"` and `"orange | cushions placed …"`. A longer natural-prose probe had 9 mid-sentence transitions out of 9.
- **[VF] This was introduced by commit `60d5002`, which replaced the production sentence-aware calls with the offset chunker to support highlighting/playback.** The regression retained XTTS `split_sentences=True`, creating two segmentation layers: an application fragment boundary followed by Coqui's PysBD sentence segmentation.

### Causal interpretation and remaining uncertainty

**Deepest proven application cause:** the offset/highlighting feature discarded the prior sentence-boundary invariant. The app now asks generative TTS engines to synthesize incomplete sentence fragments at nearly every 280-character chapter boundary.

**Mechanism consistent with the sparse symptom [INF]:** XTTS v2 is an autoregressive sampled decoder (`TTS==0.22.0`); the pinned implementation invokes `generate(..., do_sample=True, repetition_penalty=...)`. Incomplete fragments make a minority of boundaries vulnerable to decoder continuation/repetition. Coqui then receives those fragments with `split_sentences=True`. This fits a few anomalies per chapter rather than a repeat-every-item product rule.

**Not claimed:** the controlled XTTS probe did not reproduce a literal duplicate on its single seed. It did confirm that app-style fragments are handed to the model exactly at the unsafe boundaries. A same-input control with Coqui splitting disabled omitted trailing sentences, so disabling its splitter is not a safe fix. Without the affected input/audio/engine selection, no review can attribute each emitted duplicate to XTTS rather than a source PDF's repeated headers/footers. The correction removes the confirmed risk while preserving Coqui splitting; a residual report must include input excerpt, output WAV, selected engine/voice, and source type.

The implementation is therefore a **causal-risk correction**, not a claim that it deterministically reproduces every reported waveform. Its deterministic acceptance criteria prove that no application-owned input is duplicated and that normal chapter batches end at grammatical boundaries; they do not promise to eliminate all model hallucinations.

## Corrective design

Replace the word-only partitioning policy inside `chunk_text_with_offsets`, retaining its `TextChunk(text, start, end)` contract. The parser is deliberately an offset-preserving selector over the existing `\S+` word spans; it must not use `sentence_split` because that function strips and normalizes source text.

1. Start at the same word-aligned `start_offset` as today.
2. A **terminal boundary** is the end of a word whose source suffix is `[.!?;:]` optionally followed by closing quotes/brackets, then whitespace or end-of-text. A period in the explicit abbreviation set `{Mr., Mrs., Ms., Dr., Prof., Sr., Jr., St., vs., etc., e.g., i.e.}` or an all-initials token such as `U.S.` is not terminal. A **paragraph boundary** is two newline separators with optional spaces/tabs; it has the same priority as terminal punctuation. Quotation marks and bracket closers remain inside the preceding chunk.
3. When adding the next word would exceed `max_chars`, select the latest fitting terminal/paragraph boundary since the current chunk start. If none fits, select the latest fitting **clause boundary** (a comma or closing parenthesis followed by whitespace); only then use the latest fitting word. An individual word longer than the limit is emitted alone, matching current behavior.
4. A nonzero `start_offset` first snaps forward to the same word start as today; it never expands backward to an earlier sentence. It then applies the priority rules only to the remaining suffix.
5. Build each `TextChunk` exactly as `source[chunk.start:chunk.end].strip()`, from monotonically increasing non-overlapping source ranges. Whitespace between ranges is intentionally unowned; no other source character or word can be skipped, normalized, or repeated. Do not change engine calls.
6. Keep XTTS `split_sentences=True`; the application owns coarse, complete-sentence batches and Coqui safely handles its own sentence-level synthesis.

## Implementation steps

1. Add a committed fixture, `tests/fixtures/chapter_boundary_regression.txt`, containing the eight unique-marker sentences from the controlled probe. Write failing unit tests with its exact expected chunk end positions; the old chunker must demonstrate the two bad transitions (`fourth unique | sentence describes` and `orange | cushions placed`), while the new chunker must end its non-fallback chunks after `library.`, `cabinet.`, and `field.`. Assert every `chunk.text == source[chunk.start:chunk.end].strip()`, monotonic non-overlap, intentional whitespace-only span gaps, and exact word reconstruction.
2. Add failing unit tests for paragraph/quote/abbreviation boundaries, clause then word fallback for an over-limit sentence, an individual over-limit token, and a `start_offset` in the middle of a sentence. The expected outcomes must encode the boundary rules above rather than merely assert a maximum count.
3. Refactor `chunk_text_with_offsets` only. Use existing word spans and local terminal/paragraph/clause selectors. Leave `TextChunk`, engine APIs, and `split_sentences=True` unchanged.
4. Add service-level mocks for XTTS, Piper, and Pocket. Each engine must receive exactly the expected fixture `TextChunk.text` sequence once, and the yielded chunk count must equal the input chunk count. Add coordinator/main-generation and document-wizard tests with a fake segment per chunk to assert their expected chunk counts and each segment is appended once. This gives every shared engine the same deterministic boundary acceptance check; the intentional tradeoff is shorter chunks when needed for sentence context, not a throughput guarantee.
5. Restore the language-learning defaults, dataclass fallbacks, wizard fallback, handoff default, README wording, and related tests to their pre-`8060d77` state. Replace this plan's prior false RCA rather than retaining it as a completed incident.
6. Run focused chunking, engine-service, document-pipeline, language-learning, and settings tests. Then run the full suite, Ruff, and `git diff --check`.
7. Optionally run the documented diagnostic—not a quality gate—only on a machine with the locally cached XTTS v2 model and `openai/whisper-tiny`: set `torch.manual_seed(20260801)`, synthesize `tests/fixtures/chapter_boundary_regression.txt` with `Ana Florence`, `language='en'`, and `split_sentences=True`; record audio plus Whisper transcript outside the repository. Acceptance is the eight unique marker sentences in source order with no duplicate marker. The test must name the Python/transformers versions and command in the outcome, and a failure is evidence to investigate rather than an automatic model-setting change.
8. Record RED/GREEN commands and results in this plan, request an independent advisor review, then commit only if it clears.

## Test plan

- `tests/test_text_chunking.py` and `tests/fixtures/chapter_boundary_regression.txt` — exact span invariant, terminal/paragraph/quote/abbreviation selection, long-sentence fallback, and start-offset behavior.
- `tests/test_full_pipeline.py` — extracted document text remains chunkable with exact source-range ownership and whitespace-only inter-span gaps.
- Engine-service tests — XTTS, Piper, and Pocket each receive the identical expected offset-preserving chunk sequence once and yield one segment per input chunk.
- `tests/test_app_logic.py` / document-wizard test — the main and document-wizard assemblers consume each fake yielded segment once and retain their chunk-count/progress alignment.
- `tests/test_language_practice_integration.py`, `tests/test_language_learning_wizard.py`, `tests/test_settings.py` — restore the intentional language-learning repetition defaults and explicit opt-out behavior.
- `.venv/bin/python -m pytest tests/test_text_chunking.py tests/test_full_pipeline.py tests/test_app_logic.py tests/test_wizard_logic.py tests/test_xtts_service.py tests/test_piper_service.py tests/test_pocket_service.py tests/test_language_practice_integration.py tests/test_language_learning_wizard.py tests/test_settings.py`
- `.venv/bin/python -m pytest`, `.venv/bin/ruff check .`, `git diff --check`.

## Risks and rollback

Boundary selection may yield shorter chunks when a sentence ends early; this trades a small amount of throughput for grammatical context at the model boundary. Long sentences retain the existing clause/word fallback and character-limit behavior. Highlighting offsets remain exact because every chunk still points into the untouched original string.

Rollback has two explicit independent units: (1) restoring the prior word-only `chunk_text_with_offsets` plus the new fixture/chunk/engine regression tests restores the prior shared-engine boundary behavior; (2) reapplying `8060d77` restores language-learning's opt-in default if that separate product decision is later desired. This corrective commit itself restores the pre-`8060d77` repeat-by-default behavior. No model weights, decoder parameters, user settings migration, or generated files are changed.

If the symptom remains after this change, do not tune decoder parameters blindly. Compare the source text, selected engine, emitted chunk ranges, and affected waveform/ASR around the timestamp. For PDFs, first check the extracted text for repeated headers/footers.

## Plan score — revision 2: 96/100

- Evidence grounding: 29/30 — all synthesis paths, span construction, historical regression, and live probe are directly inspected; the model-hallucination link is explicitly labeled inference and the executable fixture carries the observed boundaries.
- Required structure: 15/15 — RCA, scope, implementation, verification, risks, rollback, and residual investigation are present.
- Concreteness: 20/20 — exact recognition, priority, start-offset behavior, fixture, source-range invariants, and optional probe prerequisites are specified; implementation intentionally avoids speculative decoder knobs.
- Risk and reversibility: 15/15 — source spans, Coqui splitting, two independent rollback units, settings restoration, and fallback behavior are explicit.
- Test coverage: 10/10 — deterministic unit invariants plus three-engine, main/document assembly integration and a bounded optional live diagnostic.
- Scope discipline: 7/10 — it corrects the shared chunker for all engines because that is the shared regression and validates each; it deliberately does not claim a stochastic decoder reproduction without an affected artifact.

## Advisor review

Revision 1 was blocked at 78/100 because it overreached from a proven risk factor to an unproven waveform root cause and left parser, fixture, shared-engine, rollback, and optional-model-probe details incomplete. Revision 2 explicitly bounds the claim, specifies the offset parser and deterministic fixture/invariants, validates all three consumers, and makes the live probe reproducible but non-gating.

**Independent advisor disposition:** Cleared at 94/100 on 2026-08-01. The advisor confirmed the bounded causal claim, parser contract, fixture/invariants, cross-engine and assembler checks, separate rollback units, and non-gating diagnostic. It requested only that the focused command name all new service and wizard test modules; the command above incorporates that polish.

## Implementation outcome

- Replaced word-only production chunk selection with exact-offset sentence/paragraph-first selection. It prefers terminal/paragraph boundaries, then clauses, then words; it ignores configured abbreviations and all-initials periods as terminal boundaries. It preserves the existing forward word-aligned `start_offset` semantics and keeps individual long words intact.
- Kept Coqui XTTS `split_sentences=True`. The application now supplies complete sentence batches whenever possible rather than disabling the engine's sentence processing.
- Added the committed eight-marker chapter fixture plus exact range, whitespace-gap, reconstruction, quote, paragraph, abbreviation, clause, word-fallback, start-offset, and long-token regression coverage.
- Added XTTS, Piper, and Pocket service tests that assert each receives the same corrected chapter chunks exactly once, plus main-generation and document-wizard assembly tests that assert each yielded segment is appended once.
- Reverted the unrelated `8060d77` language-learning default change in code, README, and its tests; target repetition is again the existing default within the explicit language-learning workflow.

## Verification results

- RED: before the parser change, `tests/test_text_chunking.py` failed the committed chapter-boundary assertion with old spans `0-272`, `273-548`, `549-670` rather than the required complete-sentence spans, and failed the paragraph-boundary assertion.
- GREEN: `.venv/bin/python -m pytest` passed **472 tests**; `.venv/bin/ruff check .` and `git diff --check` passed.
- GREEN optional diagnostic: with cached XTTS v2, `Ana Florence`, English, `split_sentences=True`, and `torch.manual_seed(20260801)`, the corrected fixture formed three chunks ending after `library.`, `cabinet.`, and `field.`. Whisper tiny transcribed all eight unique marker sentences in source order with no duplicate marker. Environment: Python 3.11.9, transformers 4.46.3. The generated WAV/transcript are retained only under `/tmp/tts-boundary-audit.pOLzx4`, outside the repository.
