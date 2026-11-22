# Plan: Audio/Video Dubbing Studio (EN->HU local)

**Type:** Feature plan
**Date:** 2026-11-22
**Status:** Implemented and verified (Phase 1a + 1b audio path; video mux behind phase_1b gate)
**Branch:** `feature/av-dubbing-studio`

## Summary

Local-first Dubbing Studio. User-locked: MVP plus optional separation (toggle default OFF), no diarization/lip-sync in v1; STT faster-whisper; translation NLLB-200-1.3B; spellcheck cyhunspell; EN->HU must work; Pocket disabled for HU.

Phased: 1a audio-only EN->HU (import, transcribe, translate, review, TTS, stretch, mix, mp3/wav + SRT). 1b video mux + burn-in. Enforcement: `DEFAULT_DUBBING_SETTINGS.phase_1b_enabled=False`; wizard video-import + burn-in widgets hard-disabled unless flag True AND 1a acceptance recorded in plan; 1b code lives in `dubbing/video.py` which 1a never imports (test asserts `sys.modules` has no `dubbing.video` after 1a run).

## Steps

1. `dubbing/` package, lazy imports, base `requirements.txt` untouched:
   - `dubbing/__init__.py` — `SUPPORTED_INPUT_EXTS`, `SUPPORTED_VIDEO_EXTS`, probes: `ffmpeg_path()`, `has_libass()` functional gate (see verification below), `has_faster_whisper()`, `has_nllb()`, `has_separator()`, `has_cyhunspell()`.
   - `dubbing/config.py` — `DEFAULT_DUBBING_SETTINGS={target_lang:hu, engine:Auto, burn_in:False, keep_bg_ratio:0.2, separation_enabled:False, whisper_model:small, audio_output_format:mp3, video_output_format:mp4, phase_1b_enabled:False}` (separate audio/video outputs; 1a default is audio-only mp3 — never mp4); `DubJob`, `Segment(start,end,text,translated)`; validation rejects bad ext, hu+pocket, burn_in with audio-only output. Single field name `keep_bg_ratio` everywhere.
   - `dubbing/stages.py`:
     - `extract_audio(src, tmp, sr=44100)` — `ffmpeg -i src -vn -ar 44100 -ac 1 tmp.wav`.
     - `separate_background(wav, tmp, enabled)` — OFF returns `(wav,None)`; ON uses `audio-separator==0.48.0` (verified via `pip index versions audio-separator` 2026-11-22: 0.48.0 latest, 0.1.0 does NOT exist) UVR-MDX `kim_vocal_2` (~300MB, MIT per repo; N/A reason for line cite: external PyPI, verified by pip index, not in tree). CPU fallback documented as 10-50x realtime — toggle warns when no CUDA.
     - `transcribe(vocal, model_size="small")` — `faster-whisper==1.2.1` (verified: 1.2.1 latest, 1.0.3 also exists; pin 1.2.1; MIT; N/A line cite: external PyPI). Models: `small` 244M params ~466MB int8 default, `base` 74M ~145MB fallback, `medium` 769M ~1.5GB advanced. Word timestamps preserved.
     - `translate_segments(segs, src=eng_Latn, tgt=hun_Latn)` — `facebook/nllb-200-1.3B` (~2.5GB, CC-BY-NC-4.0 + custom research terms — see license note below), NLLB SentencePiece tokenizer budget: `max_new_tokens=int(1.6 * sp_len(src))` using `NllbTokenizer`; never word-count.
     - `synthesize_segment(...)` — delegates to `SynthesisCoordinator` (`app.py:2397`) via `select_engine` (`app.py:2072`); XTTS `app.py:2097`, Piper `app.py:2185`, Pocket `app.py:2256` blocked for hu.
     - `fit_to_slot(dub_wav, slot_dur)` — `r=dur/slot`; accept 0.85-1.15; else chain atempo each in [0.5,2.0]: while r>2.0 emit 2.0; while r<0.5 emit 0.5; final r; 80ms pad; overflow ONLY when `dur>2.5*slot` (r>2.5, too long). Corrected expectations: r=3.0 -> [2.0,1.5]; r=0.2 -> [0.5,0.5,0.8] NO overflow; r=5.0 -> [2.0,2.0,1.25] + overflow. Never bleed into next start.
     - `mux_export(...)` — unique timestamped outputs, `.part` rename-on-success, no bare `-y`; mp4 soft subs `-c:s mov_text`, mkv soft subs `-c:s srt`; burn only if `has_libass()` else sidecar fallback.
   - `dubbing/subtitles.py` — `write_srt`, `parse_srt`, `srt_norm_hash()` = sha256 of NFC-normalized `start,end,text` tuples (floats rounded to ms) — hash covers content not byte layout; `build_burn_filter()` escapes per ffmpeg: backslash `\\`, colon `\\:`, single-quote `\\'`, wraps path in single quotes; Windows `C:\` becomes `C\\:/...` and drive-colon escaped; test includes `C:\My Vids\teszt srt.srt`. SRT always; VTT deferred.
   - `dubbing/spellcheck.py` — `cyhunspell==1.3.4` (verified latest via pip index); dicts `hu_HU` magyarispell/hunspell-hu (~2MB, GPL/LGPL/MPL tri-license — download prompt, never vendored), `en_US` fallback; missing -> `available==False` banner.
   - Download gate: `confirm_model(id,size_mb,license)` before first download: whisper-small 466MB MIT, NLLB-1.3B 2500MB CC-BY-NC, separator 300MB MIT. Weights in `~/.cache/huggingface`, `~/.cache/audio-separator`; Guide has Clear-cache button.
2. `app.py` wiring, feature-flagged lazy import:
   - Toolbar `app.py:5050`: File after `app.py:5067`, Tools after `app.py:5156`, Help menu `app.py:5161` / About `app.py:5162` add Guide entries; all call `open_dubbing_wizard()` with ImportError hint. Opener mirrors `app.py:5955`; wizard pattern `app.py:2896`. Pocket guard via `app.py:98`, `app.py:138`, `app.py:142`.
   - `dubbing/ui_wizard.py`: segment table, Translate, F7 spellcheck, voice panel, burn-in checkbox enabled only if input in VIDEO_EXTS and output video and `has_libass()` and `phase_1b_enabled`, else disabled with reason tooltip.
   - Threading: worker + `root.after` flush, ffmpeg killed on Stop, temp dir cleaned.
3. Deps/setup/docs:
   - `requirements-dubbing.txt`: `faster-whisper==1.2.1`, `transformers==4.46.3` (base `requirements.txt:8`), `sentencepiece`, `srt`, `cyhunspell==1.3.4`, `audio-separator==0.48.0` optional; `numpy==1.26.4` (base `requirements.txt:7`); `torch==2.5.1` from `setup.sh:84` reused.
   - `setup.sh` after `setup.sh:85`: `--with-dubbing` installs dubbing file; `setup.ps1` after `setup.ps1:41` (requirements) with torch at `setup.ps1:35/38`: same flag. Smoke test `python -c "import faster_whisper,transformers,audio_separator"` manual (no CI in repo — N/A reason: repo has no CI config in tree).
   - License note (repo `LICENSE` is AGPL): NLLB CC-BY-NC weights are downloaded locally at user action, never vendored/redistributed; Guide states non-commercial local use only, user confirms license; fixture uses Piper voice, no NC weights in repo/CI.
   - Settings: `DEFAULT_DUBBING_SETTINGS` + extend `normalize_app_settings` (`app.py:1744`), `_default_settings_dict` (`app.py:1664`); load `app.py:1646`, save `app.py:1782` (+`.bak` `app.py:1782-1793`, corrupt backup `app.py:1651-1660`).
   - Perf: whisper-small ~1x realtime CPU, NLLB ~2-5s/segment CPU, XTTS ~3x slower than realtime (`app.py:182` precedent); disk ~3.5GB Phase 1a. External estimates — N/A line cite: vendor model cards, stated as estimates not guarantees.
4. Verification: `python -m compileall -q app.py dubbing tests`, `ruff check app.py dubbing tests`, `pytest -q tests/test_dubbing_*.py`, full `pytest -q`, `git diff --check`. libass gate verified 2026-11-22 on bundled static ffmpeg `ffmpeg-linux-x86_64-v7.0.2` (`app.py:27` wiring via imageio-ffmpeg): `-h filter=subtitles` exit 0 documents libass; `-filters` lists `subtitles` + `ass` (libass); functional 1s burn-in `color=s=320x240:d=1 + subtitles=burntest.srt (Teszt ekezes) -> libx264/aac burntest.mp4 2725 bytes` succeeded. `has_libass()` implements: (a) `-h filter=subtitles` exit 0 AND mentions `libass`, (b) cached functional 1s burn-in on first enable; parse rule explicit in code.

Out of scope: pyannote, MADLAD/EuroLLM, lip-sync.

## Verification results

- Plan gate: subagent adversarial 95/100, no blockers (cycle 3); Luna extra review 94/100 Ready.
- libass proven on bundled ffmpeg 7.0.2 (`-h filter=subtitles` + functional 1s burn-in 2725B MP4).
- Pins verified via pip index 2026-11-22: faster-whisper 1.2.1, audio-separator 0.48.0, cyhunspell 1.3.4.
- GREEN: `python -m compileall -q app.py dubbing tests`; `ruff` on changed files; `pytest -q` 532 passed (incl. 12 new dubbing + 4 updated settings); `git diff --check`.

## Risks and rollback

GB downloads gated + sizes + license + cache paths + Clear button; revert deletes `dubbing/` + menu hunks, weights/partial outputs documented as manual clear. libass proven present in bundled binary (see verification) with functional fallback to soft-sub. Pins verified by pip index; same torch/numpy as base. Lazy import guards toolbar. Timestamped outputs, `.part` cleanup, burn-in warns generation loss. Settings merge preserves unknown keys. NC-license: no vendoring, local-download only. Separator CPU cost warned at toggle.

## Test plan

- `tests/test_dubbing_config.py`, `test_dubbing_subtitles.py` (accents, Windows path escaping, mp4 `mov_text` + mkv `srt` mux args, norm-hash not byte-hash), `test_dubbing_spellcheck.py`, `test_dubbing_pipeline.py` (corrected: r=3.0->[2.0,1.5], r=0.2->[0.5,0.5,0.8] no overflow, r=5.0->[2.0,2.0,1.25]+overflow; separator OFF identity; stop kills ffmpeg), `test_dubbing_wizard_logic.py` (hu disables pocket; burn matrix incl. phase flag; overflow surfaces; 1a never imports `dubbing.video`).
- Fixture `scripts/make_dub_fixture.py`: 30s Piper EN wav, 3 known segments, expected norm-hash; assert count 3, no overlap, ±120ms after fit, SRT parses. Phase-isolation test runs in an isolated subprocess (`python -c "import dubbing.pipeline"`) so `sys.modules` is order-independent (fixes shared-pytest-process flakiness).
- Manual: fixture EN->HU burn on/off; missing-dep via hidden import.

## Standards & Guardrails Evidence

- Toolbar `app.py:5050`, File `app.py:5067`, Tools `app.py:5156`, Help `app.py:5161`/About `app.py:5162`; wizard `app.py:2896`, opener `app.py:5955`; engines `app.py:2072`, `app.py:2097`, `app.py:2185`, `app.py:2256`, `app.py:2397`; Pocket `app.py:98`, `app.py:138`, `app.py:142`; perf `app.py:182`; ffmpeg `app.py:27`, settings const `app.py:203`, load `app.py:1646`, defaults `app.py:1664`, normalize `app.py:1744`, save `app.py:1782`; pins `requirements.txt:7`, `requirements.txt:8`; torch/pip `setup.sh:84-85`, `setup.ps1:35/38/41`; AGPL `LICENSE`. External versions/sizes/licenses: N/A in-tree reason — verified via `pip index versions` (faster-whisper 1.2.1, audio-separator 0.48.0, cyhunspell 1.3.4) and live ffmpeg probe 2026-11-22, recorded above.
