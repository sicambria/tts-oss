# RCA: stop default duplicate sentences in language-learning audio

**Type:** RCA
**Date:** 2026-08-01
**Branch:** `fix/audio-output-duplication`
**Worktree:** `/home/arsvivendi/git/tts-oss-wt/audio-output-duplication`
**Current status:** Implemented and verified

## Summary

The reported intermittent duplicate output has a deterministic application-level candidate in the language-learning flow, distinct from unproven XTTS decoder repetition. A language-practice session is active only after language-learning handoff. Its default `repeat_target_sentence=True` causes the app to add the target sentence twice before optional English translation, and the export/read-aloud paths synthesize every resulting request. Normal editor synthesis does not use that sequence, which explains why the symptom occurs only sometimes.

The fix changes target repetition from a default to an explicit opt-in. Existing saved `true` values are preserved and treated as opt-in; absent settings and new sessions will synthesize each target sentence once. The checkbox remains available for deliberate spaced-repetition practice. Because a prior default `true` cannot be distinguished from an intentional choice, this plan does not silently reset persisted settings. For the current affected configuration, the user must uncheck `Repeat target sentence before English translation` once; the updated README will state that action. If the reported duplication is observed with no active language-learning session, this plan is a separately useful default-UX correction but not the causal fix; capture that input, engine, voice, and output artifact and reopen the XTTS-specific RCA before modifying decoder settings.

## Scope

- Change the language-learning default and all fallback/default constructors from target repetition enabled to disabled.
- Retain explicit `repeat_target_sentence=True` behavior and its UI control.
- Update the user-facing usage note and regression tests.

Out of scope: XTTS decoder/sampling configuration, text chunking, Piper/Pocket behavior, audio post-processing, and changing an existing explicit user setting.

## Root Cause Analysis

**Trigger [VF]:** A language-learning session is activated, then the user reads aloud or exports its generated pairs while target repetition remains at its default. `App.activate_language_practice` creates a `LanguagePracticeSession` with its default repetition flag at `app.py:4589`; `DEFAULT_LANG_LEARNING_SETTINGS` defines that default as enabled at `app.py:193`.

**Deepest causal node [VF]:** `App.practice_speech_items` appends a second `SpeechItem` with the exact same target text whenever `session.repeat_target_sentence` is true at `app.py:5155`. `run_practice_generation` synthesizes each resulting request in order at `app.py:5550`, so exported audio contains that target twice. The same item sequence feeds practice read-aloud at `app.py:5327`.

**Why it was possible [VF]:** Tests and the README currently encode the repeat-by-default behavior: the request sequence has duplicate target-language entries in `tests/test_language_practice_integration.py:103`, and the usage note describes it at `README.md:109`. Five fallback/default sites all enable repetition: `DEFAULT_LANG_LEARNING_SETTINGS` (`app.py:208`), `LanguageSessionConfig` (`app.py:1189`), `LanguagePracticeSession` (`app.py:1198`), wizard initialization (`app.py:3202`), and handoff (`app.py:4589`). This is a product-default mismatch with the user's expectation, not a missing engine safeguard.

**Competing hypothesis ruled out for this change [OBS]:** XTTS is invoked after request construction (`app.py:1913`); the duplicate `SpeechItem` sequence is engine-independent and is also sent to Piper/Pocket. The pinned Coqui API (`requirements.txt:1`) may have separate decoder-repetition behavior, but no model artifact or reproducible XTTS-only case connects it to this report. It is therefore not changed speculatively; a future XTTS-only report should capture input, engine, voice, and generated artifact before tuning decoder parameters.

## Implementation Steps

1. Write failing tests that take unconfigured normalized settings through the wizard repeat variable, handoff, and `practice_requests`, then assert target/English occurs once. Assert a default `LanguagePracticeSession` also emits target/English once, while an explicit `True` retains target-target-English. Update the absent-setting test to expect `False` and add a persisted-true compatibility test; confirm the pre-fix tests fail.
2. Set `repeat_target_sentence=False` at each default/fallback site: `DEFAULT_LANG_LEARNING_SETTINGS`, `LanguageSessionConfig`, `LanguagePracticeSession`, wizard initialization, and `activate_language_practice`. Preserve explicit persisted `True` values through `normalize_app_settings`.
3. Update the README usage note to describe target repetition as an opt-in checkbox and tell existing users of the old default to uncheck it once. This is the documented acceptance action for persisted `true` settings.
4. Run focused settings, wizard, and practice-integration tests; run the full pytest suite and Ruff check. The behavioral acceptance check is the complete request sequence, not a mocked engine argument.
5. Record the RED/GREEN results, final score, and advisor disposition in this plan before committing plan, tests, code, and README together.

## Risks and Reversibility

The change affects only new or unconfigured language-learning sessions. All saved `true` values are preserved and treated as opt-in because the application cannot determine whether they were set intentionally or inherited from the prior default; current users who do not want repetition must uncheck the existing option once. Users who want the learning cadence can keep or check it. The only behavioral tradeoff is that newly generated practice audio no longer repeats targets by default. Rollback is a one-line restoration of the default, but it would restore unexpected duplicate audio. No data migration, deletion, or engine/model change occurs.

## Test Plan

- `tests/test_language_learning_wizard.py::TestLanguageLearningWizardSettings::test_collect_settings_defaults_target_repetition_to_disabled` — unconfigured normalized settings feed the wizard's repeat value, RED before the fix.
- `tests/test_language_practice_integration.py::TestLanguagePracticeMainFlow::test_handoff_defaults_to_one_target_utterance` — handoff default regression, RED before the fix.
- `tests/test_language_practice_integration.py::TestLanguagePracticeMainFlow::test_default_session_emits_target_then_translation_once` — complete pre-engine request-sequence regression, RED before the fix.
- `tests/test_language_practice_integration.py::TestLanguagePracticeMainFlow::test_repeat_target_sentence_can_be_enabled` — explicit opt-in preserves target-target-English behavior.
- `tests/test_settings.py::TestSettingsMigration::test_target_sentence_repetition_defaults_to_disabled` and `test_explicit_target_sentence_repetition_is_preserved` — absent-setting default and persisted-true compatibility.
- `pytest tests/test_language_practice_integration.py tests/test_language_learning_wizard.py tests/test_settings.py` — focused behavior suite.
- README acceptance check — the usage note says new sessions speak targets once and gives the exact existing-user action to turn off a preserved `true` value.
- `pytest` and `ruff check app.py tests/test_language_practice_integration.py tests/test_language_learning_wizard.py tests/test_settings.py` — full and static verification.

## Standards & Guardrails Evidence

- [x] Schema & migrations: `app.py:1401` merges persisted settings with defaults; no database/schema migration is involved, and explicit settings remain preserved.
- [x] Cleancode budgets: `app.py:193` is the centralized language-learning default, while `app.py:5134` is the single request-sequence builder; the fix changes defaults rather than adding a parallel audio path.
- [x] i18n & locales: `app.py:5157` and `app.py:5167` preserve existing target/English language routing; only target repetition count changes.
- [x] Tests / shift-left: `tests/test_language_practice_integration.py:103` already asserts the practice request ordering, which is the cheapest deterministic layer for duplicate-output behavior.
- [x] GDPR & security: N/A — no user-data collection, persistence schema, authentication, network request, or model download behavior changes.
- [x] Reused patterns / grounding: `app.py:3608` independently repeats the target under the same flag in the legacy wizard export helper; its default configuration flows from `LanguageSessionConfig` at `app.py:1182` and is included in the default audit.

## Plan Score — Revision 5: 97/100

- Evidence grounding & dimension coverage: 30/30 — the direct duplication site, every default site, session activation, both synthesis consumers, existing behavioral test, and README all have resolving current-tree citations; the XTTS theory is explicitly bounded as unproven.
- Required structure: 15/15 — complete RCA, scope, steps, risks, test plan, and six evidence dimensions; no placeholders.
- Concreteness & verifiability: 20/20 — explicit RED behavior tests cover normalized setting through wizard/handoff, default request sequence, explicit opt-in, and full verification commands.
- Risk & reversibility: 15/15 — the non-destructive compatibility decision, current-user action, retained opt-in, and rollback are all explicit.
- Test / shift-left coverage: 10/10 — tests cover the default, explicit opt-in, settings fallback, and complete pre-engine request sequence.
- Scope discipline: 7/10 — the scope correctly excludes unproven XTTS tuning and does not add a destructive settings migration; the report still does not explicitly identify its originating flow, so the fallback RCA remains necessary.

## Advisor Review

Revision 2 was blocked because its XTTS theory had no reproduction and did not exclude decoder repetition or context-limit risks. Revision 3 found the deterministic, engine-independent duplicate-request path, but did not prove the report originated there or test the whole settings-to-handoff chain. Revision 4 recorded the validation decision and tests that chain, but did not make the current-user action explicit. Revision 5 preserves stored settings non-destructively and documents the exact one-time action required for existing `true` values. An independent re-review is required before implementation.

**Independent advisor disposition:** Cleared on 2026-08-01 at 96/100. The review confirmed the deterministic duplicate-request path, default-site coverage, persisted-setting compatibility, and fallback for a report observed outside language learning. No material blocker remains.

## Implementation Outcome

- Changed all five language-learning repeat defaults/fallbacks to `False`: centralized settings, both session dataclasses, wizard fallback, and handoff default.
- Preserved an explicit persisted `repeat_target_sentence: true`, so existing users who want the cadence keep it; the README now tells users of the old default exactly how to turn it off.
- Updated the request-sequence tests to expect one target utterance by default, retained explicit target repetition coverage, and added normalized-default plus persisted-true coverage.

## Verification Results

- RED: `/home/arsvivendi/git/tts-oss/.venv/bin/python -m pytest tests/test_language_practice_integration.py tests/test_language_learning_wizard.py tests/test_settings.py` produced 6 expected failures before the implementation: handoff default, default request sequence, target-only sequence, normalized default, English fallback index, and settings default.
- GREEN: the same focused command passed 41 tests after implementation; `/home/arsvivendi/git/tts-oss/.venv/bin/ruff check app.py tests/test_language_practice_integration.py tests/test_language_learning_wizard.py tests/test_settings.py` passed.
- GREEN: `/home/arsvivendi/git/tts-oss/.venv/bin/python -m pytest` passed all 463 tests; `/home/arsvivendi/git/tts-oss/.venv/bin/ruff check .` and `git diff --check` passed.
