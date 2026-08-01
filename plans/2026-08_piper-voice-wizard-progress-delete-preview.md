# Plan: Piper Voice Wizard — download progress, voice deletion, sound preview

**Type:** Feature plan
**Date:** 2026-08-01
**Status:** Implemented and verified
**Branch:** `feat/piper-wizard-progress-delete-preview` off `main`

## Summary

Three UX gaps in `PiperVoiceWizard` (`app.py:2181`):

1. **No download progress.** `_download_voice_worker` (`app.py:2325`) downloads the `.onnx`/`.onnx.json` pair through `urlopen` + `shutil.copyfileobj` with only a status string ("Downloading …") and no byte progress. A 60–120 MB model looks frozen for minutes.
2. **No deletion.** Voices downloaded via the wizard accumulate forever; the only removal path is manual file deletion outside the app.
3. **No preview.** `README.md:157` points at the piper-samples site, but the wizard itself has no way to hear a voice before or after install.

## Design

### 1. Download progress

New module-level pure helpers (testable, coverage-counted) placed near `discover_local_piper_voices` (`app.py:1636`):

- `piper_download_files(voice_info, voice_dir) -> list[PiperDownloadFile]`, where `PiperDownloadFile` is a tiny namedtuple `(rel_path, local_path, size_bytes)`. It filters the catalog `files` dict (which maps `rel_path -> {"size_bytes", …}`, confirmed against the live `voices.json`) to `.onnx`/`.onnx.json`, skips already-present non-empty local files, and preserves catalog order.
- `stream_download(url, dest, on_progress, chunk_size=131072)` — reads `urlopen(url)` in chunks, writes to `dest`, and calls `on_progress(done_bytes, total_bytes)` after each chunk. Total is the catalog `size_bytes`; if a file lacks it, fall back to `Content-Length`, and if that is also absent, report `total_bytes=0` so the UI can show an indeterminate bar.

Wizard changes:

- Add a determinate `ttk.Progressbar` plus a percentage `StringVar` in the actions row of `_build_ui` (`app.py:2206`), shown only while a download is active.
- Rewrite `_download_voice_worker` (`app.py:2325`): compute the effective file list and total byte count once, then stream each file with `on_progress`; schedule UI updates via `window.after(0, …)` throttled to ~4/s (`time.monotonic()` guard), force a final 100%, and disable the Download button while `self.downloading` is set.
- No-op case: if every file already exists (non-empty), report "already installed" without touching the bar.

### 2. Deletion of installed voices

Pure helpers:

- `piper_voice_files(voice_code, voice_dir) -> list[Path]` — the `.onnx` and `.onnx.json` paths for a voice.
- `is_bundled_piper_voice(voice_code) -> bool` — True when the code is one of the three `PIPER_VOICE_OPTIONS` codes (`app.py:165`).
- `delete_piper_voice(voice_code, voice_dir) -> list[Path]` — unlinks the pair, tolerating already-missing files, and returns the removed paths.

Wizard `delete_selected()`:

- Not installed → `show_info` "Only installed voices can be deleted."
- Bundled → `show_info` that the voice ships with the app and is restored by the setup script (see flagged decision below).
- Otherwise `ask_yes_no` naming the voice and the exact files → `delete_piper_voice` → if the deleted voice's label equals `settings["default_piper_voice_label"]`, reset it to `DEFAULT_PIPER_VOICE_LABEL` and `save_app_settings` → `app.reload_piper_voices()` (`app.py:5052`, which already falls the main-window selection back to `DEFAULT_PIPER_VOICE_LABEL` when the current label vanished) → `apply_filters()` → status. Blocked while `self.downloading`.

### 3. Sound preview

Pure helpers:

- `piper_sample_url(voice_code, voice_info=None) -> str` → `https://rhasspy.github.io/piper-samples/samples/{family}/{lang}/{name}/{quality}/speaker_0.mp3`. Prefers catalog `language.code`/`name`/`quality`; falls back to splitting the code on `-`. Each segment is URL-quoted via the already-imported `quote` (`app.py:20`). Live-verified for `en_US-lessac-medium`, `hu_HU-anna-medium`, and the non-ASCII `pt_PT-tugão-medium` (all HTTP 200; `tugão` must be percent-encoded).
- `piper_preview_text(language) -> str` — one short fixed sentence per language for the languages the app commonly serves (`en`, `hu`, `pt`, `de`, `es`, `fr`), English fallback otherwise.

Wizard actions:

- **"Open sample page"** button → `webbrowser.open_new_tab(piper_sample_url(...))` inside try/except `show_error`, mirroring `App.open_repository` (`app.py:5021`). Works for any catalog voice, installed or not.
- **"Play sample"** button → local in-app preview for installed voices only. A background thread builds `SynthesisRequest(engine=PIPER, language=piper_language_of_code(code), piper_voice_code=code, text=piper_preview_text(lang), output_file=<output>/voice-preview-<code>-<job>.wav)`, calls `app.service.synthesize(request)` (`app.service` exists at `app.py:4367`), then `app.player.play_blocking(wav, stop_event)`, deleting the temp wav in `finally` (same pattern as `run_read_aloud`, `app.py:5592`). The button toggles to "Stop preview" while active. Not installed → `show_info` suggesting Download or Open sample page.

## Decisions flagged for review

- **Bundled voices are protected from deletion.** Rationale: `discover_local_piper_voices` (`app.py:1636`) seeds options from `PIPER_VOICE_OPTIONS` unconditionally, so deleting e.g. `en_US-lessac-medium` would leave a permanently broken (un-synthesizable) entry in the main voice dropdown while the wizard correctly shows "No". Making bundled voices file-dependent would ripple into startup defaults and language availability — out of scope unless requested.
- **Preview ships both a browser link (any voice) and local playback (installed voices).** The ask was "URL or some solution"; the URL button is the guaranteed minimum, local playback is the integrated alternative. If either is judged gold-plating, drop "Play sample" and keep the URL button.

## Implementation steps

1. Add pure helpers to `app.py` next to `discover_local_piper_voices` (`app.py:1636`): `PiperDownloadFile`, `piper_download_files`, `stream_download`, `piper_voice_files`, `is_bundled_piper_voice`, `delete_piper_voice`, `piper_sample_url`, `piper_preview_text`. No change to existing signatures.
2. Extend `PiperVoiceWizard._build_ui` (`app.py:2206`): progressbar + percent label, "🗑 Delete Installed", "▶ Play sample", "🔗 Open sample page" buttons; keep the existing Refresh / Download / Set As Default controls.
3. Rewrite `_download_voice_worker` (`app.py:2325`) to use `piper_download_files` + `stream_download` with throttled progress and the already-installed no-op path.
4. Add wizard methods `delete_selected`, `open_sample_page`, `play_sample`/`_stop_preview`, and `_preview_worker`.
5. Add `tests/test_piper_voice_wizard.py` covering every helper and every wizard branch (see Test plan).
6. Run focused tests, then the full suite with coverage, `ruff check app.py tests/`, and `git diff --check`. Never `--no-verify`.
7. Update `README.md` ("Voice Wizard" usage note and Voice Sources) and record the outcome in this plan; keep the finished plan in `plans/`.

## Test plan

- `piper_download_files`: temp dir + patched `app.PIPER_VOICE_DIR`; asserts only `.onnx`/`.onnx.json` are selected, existing non-empty files are skipped, catalog sizes are carried through, order is stable.
- `stream_download`: patched `app.urlopen` returning a fake response; asserts the destination bytes equal the source, `on_progress` is called monotonically and ends at the total, and the partial-total path yields `total_bytes=0`.
- `piper_sample_url`: with catalog info, without info (code-derived), non-ASCII name percent-encoding, family derivation from `language.code`.
- `piper_preview_text`: known languages return the map entry; unknown returns the English fallback.
- `is_bundled_piper_voice` and `delete_piper_voice`: temp dir with two fake voices; deletion removes exactly the requested pair (not the sibling voice), returns the removed paths, and tolerates a missing `.onnx.json`.
- Wizard behavior (mock app/window/tree/`_build_ui`, following the `test_wizard_logic.py:61-98` pattern): `delete_selected` not-installed guard, bundled guard, confirmed path calls `delete_piper_voice` + `app.reload_piper_voices` + default reset + `apply_filters`; `play_sample` not-installed guard (no `app.service` call) and installed path (spawns thread whose request carries `engine=PIPER`, the correct `piper_voice_code`/`language`); `open_sample_page` calls `webbrowser.open_new_tab` with the derived URL; `download_selected` starts a worker.
- Commands:
  - `.venv/bin/python -m pytest tests/test_piper_voice_wizard.py tests/test_piper_service.py tests/test_app_logic.py tests/test_wizard_logic.py tests/test_ui_helpers.py`
  - `.venv/bin/python -m pytest --cov --cov-fail-under=85` (pre-push contract), `.venv/bin/ruff check app.py tests/`, `git diff --check`.

## Risks and rollback

- **Blast radius:** `PiperVoiceWizard` and a handful of new pure helpers only. No engine, chunker, settings-format, or synthesis-path change. `settings["default_piper_voice_label"]` is only ever reset (never corrupted) when its voice is deleted.
- **Destructive action:** voice file deletion is gated behind an explicit `ask_yes_no`, names the exact files, and refuses bundled voices; files are restorable by re-downloading from the wizard or running the setup script.
- **Threading:** all cross-thread UI updates go through `window.after(0, …)` per the repo rule (CLAUDE.md); the worker only touches the filesystem, the progress callback, and `after`.
- **No-op downloads:** existing files are skipped before any byte is fetched, so a re-download never truncates a valid model.
- **Rollback:** revert the single feature commit. Downloaded/deleted voice files live under `voices/` which is untracked and unaffected.

## Plan score — revision 1: 96/100

- Evidence grounding: 29/30 — every design claim cites a resolvable `app.py` line (wizard `2181`, worker `2325`, discovery `1636`, reload `5052`, service `4367`, browser pattern `5021`); catalog `files` structure and all three sample URLs were verified live against `rhasspy.github.io`. Small deduction: the throttling cadence and percentage formatting are specified at design level, not pinned to a constant name yet.
- Required structure: 15/15 — Summary, Design, flagged decisions, numbered steps, test plan, risks, rollback all present; no placeholders.
- Concreteness & verifiability: 19/20 — every step names the exact function, line, and verification; the one soft spot is that the wizard UI row layout (bar row index) is left to implementation rather than specified.
- Risk & reversibility: 15/15 — blast radius, confirmation gate, bundled protection, no-op guard, and single-commit rollback all explicit.
- Test / shift-left coverage: 10/10 — every helper and every wizard branch has a named test; the wizard class stays coverage-omitted per `pyproject.toml`, so the pure helpers carry the counted coverage and the pre-push 85% gate.
- Scope discipline: 8/10 — the ask was three things; dual preview (URL + local playback) and the bundled-protection rule are deliberate, reviewable additions beyond the literal ask, each flagged so the advisor can veto.

## Advisor review

**Independent advisor disposition: CLEAR at 96/100 on 2026-08-01.** The advisor re-verified every `path:line` citation against the working tree, independently confirmed the three sample URLs return HTTP 200 and the catalog `files` maps `rel_path -> {"size_bytes", …}`, and found no blocking objections. Non-blocking nits, folded into this revision:

1. The preview `SynthesisRequest` must also set `piper_voice_label`, `speaker_name`, `speaker_wav` (no defaults at `app.py:1288-1297`) — the worker now constructs a complete request.
2. The download URL builder is pinned: `piper_download_url(rel_path)` reuses the existing `quote(rel_path)` pattern (`app.py:2341`) so the helper is directly testable.
3. The "already installed" no-op path now has a wizard-level test asserting the status string, not just the skip logic in `piper_download_files`.
4. The progress throttle and percent format are pinned as `PROGRESS_UPDATE_INTERVAL = 0.25` and `f"{percent:.0f}%"` so the worker test is deterministic.

## Implementation outcome

Implemented as planned, with the advisor's four nits folded in. Final locations:

- Pure helpers at `app.py:1664-1798`: `PiperDownloadFile`, `piper_download_files`, `piper_download_url`, `stream_download`, `piper_voice_files`, `is_bundled_piper_voice`, `delete_piper_voice`, `piper_sample_url`, `piper_preview_text`, plus `PIPER_PREVIEW_TEXTS` and the `PIPER_SAMPLE_URL_PREFIX`/`PROGRESS_UPDATE_INTERVAL` constants.
- Wizard: `_build_ui` (`app.py:2314`) gained a determinate progressbar + percent label (hidden while idle), and `🗑 Delete Installed`, `▶ Play Sample`, `🔗 Open Sample Page` buttons; the Download button is disabled during a download. `_download_voice_worker` (`app.py:2478`) computes the effective file list once, streams each file with byte progress throttled to `PROGRESS_UPDATE_INTERVAL`, forces a final 100%, and reports "already installed" for a no-op. `delete_selected` (`app.py:2554`), `play_sample`/`_preview_worker`/`_preview_finished` (`app.py:2590-2640`), and `open_sample_page` (`app.py:2654`) implement the remaining features.
- The completion/already-installed status is set *after* `apply_filters()` so it is not immediately overwritten by the "N voice(s) shown." counter.
- `stream_download` removes the partial destination file on failure so a later retry does not mistake a truncated download for a complete voice.
- Tests: `tests/test_piper_voice_wizard.py` (32 tests) covers every helper and every wizard branch.
- README: the `Voice Wizard` usage note and the `Voice Sources` section describe progress, deletion, and both preview paths.

## Verification results

- GREEN: `/home/arsvivendi/git/tts-oss/.venv/bin/python -m pytest` passed **515 tests**; coverage **87.7%** (pre-push gate 85%). Focused set `test_piper_voice_wizard.py test_piper_service.py test_app_logic.py test_wizard_logic.py test_ui_helpers.py`: 207 passed.
- GREEN: `.venv/bin/ruff check app.py tests/` passed; `git diff --check` clean.
- GREEN: `import app` sanity check; `piper_sample_url` returns the verified official URL and `piper_preview_text` returns the Hungarian sample sentence.
- GREEN (post-review): `piper_sample_url` derivation validated against all **171** catalog voices and the live piper-samples tree — 171/171 exact path match; every sampled voice with a sample dir also has `speaker_0.mp3`. Only `cs_CZ-kasandra-medium` has no sample upstream at all (known upstream gap, not a code issue).
- Not exercised in automation: the actual byte-streaming download, the local synthesis preview playback, and the browser-open are hardware/network paths; their logic (URL construction, chunk streaming, progress callbacks, thread start, guards, file deletion) is covered by the unit tests above. The three official sample URLs were verified HTTP 200 against `rhasspy.github.io` during planning.

## Post-implementation review (2026-08-01)

Self-review of the full diff found and fixed one real defect plus one validation pass:

- **Defect fixed:** `stream_download` previously left a partial file on a failed/interrupted download; on the next attempt `piper_download_files` would treat the non-empty partial as "already installed" and skip it, leaving a corrupt voice. `stream_download` now unlinks the partial destination on failure (new test `test_partial_download_is_cleaned_up_on_failure`).
- **Validation pass:** the official sample URL derivation was checked against the entire live catalog (171 voices) and the piper-samples file tree — every derived path matches, so `Open Sample Page` targets a real MP3 for every catalog voice that has an upstream sample.
