# PLAN: BUG — HU dub of music+speech video is unusable (hallucinated STT, wrong NLLB codes, separation never wired)

Type: BUG
Status: draft
Date: 2026-11-22
Trigger: user dubbed "~/Videók/Claude going IPO.mp4" to Hungarian — music+speech video, output audio not translated, captions gibberish.

## Summary

Fix the EN→HU dubbing path end-to-end for real-world music+speech video and prove it with a repeatable quality gate + scripts. Five root causes (3 proven by execution, 2 by code read):

1. Whisper hallucinates on music (proven): `stages.transcribe` uses auto-lang + no VAD → 8 segs on first 60 s with invented lyrics in music-only 30–50 s; with `language="en" + vad_filter=True` → 4 clean segs.
2. NLLB language-code mismatch (proven): pipeline passes `("en","hu")` but `translate_segments` expects NLLB codes; `convert_tokens_to_ids("hu")=300` (wrong) vs `"hun_Latn"=256071`; `src_lang` never set.
3. Separation never wired (code read): `pipeline.run` sets `vocal=wav`, never calls `separate_background`; `mix_with_bg` always gets `bg=None`; wizard `separation` checkbox never reaches `DubJob` (no field).
4. `DubJob` missing fields: no `separation_enabled`, no `whisper_model`, no `source_lang` mapping — wizard settings silently dropped.
5. Video mux drops original audio (code read): `mux_video` maps only dub timeline, so background music is lost even when `keep_bg_ratio>0`.

## Steps — phased (single branch, three reviewable slices)

### Phase A — STT + NLLB correctness (no new deps, biggest quality win)

1. Reproduce & lock evidence (done, keep artifacts):
   - [x] Extract audio + 60 s probe clip from user video.
   - [x] faster-whisper small auto/no-VAD vs en+VAD comparison (hallucination proven: 8 segs with invented music-only lyrics vs 4 clean).
   - [x] NLLB tokenizer id check (`hu`=300 wrong vs `hun_Latn`=256071; `src_lang` never set).
2. Fix `dubbing/stages.py` (corrected after evidence: VAD-on drops sung vocals):
   - `transcribe(vocal, model_size="small", language=None, vad_filter=False)`: VAD OFF by default — proven on the real song, Silero VAD kept 5/52 segments and deleted the whole sung body (98–229 s of real lyrics). `no_speech_prob` cannot post-filter either (real sung segs score 0.75–0.94, median 0.86). Hallucination on instrumental gaps is instead curbed with `condition_on_previous_text=False` + `hallucination_silence_threshold=2.0` (VAD-off full transcript: zero segments in instrumental gaps 22–30 s, 229–238 s). Two-way language handling — new `whisper_lang()` (`"eng_Latn"→"en"`, `"hu"→"hu"`); default language comes from `DubJob.source_lang`, never hardcoded. `vad_filter=True` stays available for spoken-only content via API. Old-version faster-whisper falls back to plain call via TypeError guard.
   - `translate_segments`: accept BOTH short (`en`/`hu`) and NLLB (`eng_Latn`/`hun_Latn`) via new `nllb_code()` mapper (`en`→`eng_Latn`, `hu`→`hun_Latn`, passthrough if already `*_Latn`/`*_Cyrl`); set `tok.src_lang = nllb_code(src)` AND `forced_bos_token_id=convert_tokens_to_ids(nllb_code(tgt))`; skip empty/whitespace segs; clamp `max_new_tokens`; model id from env `DUB_NLLB_MODEL` (default `facebook/nllb-200-1.3B`, distilled-600M fallback documented for slow CPUs; 238 s ≈ 30–40 segs ≈ ~5 min CPU on 1.3B, not hours).
   - HU length strategy (EN→HU expands ~20–30%): keep `fit_to_slot` + existing `OVERFLOW_RATIO=2.5` flag; pipeline already logs "edit the translation shorter" per overflow seg; quality gate (Phase C) fails on overflow-rate >20% so chipmunk output can't pass as green.
3. Fix `dubbing/config.py` `DubJob`:
   - Add `separation_enabled: bool=False`, `whisper_model: str="small"`; `validate()` checks `whisper_model in {"tiny","base","small","medium","large-v3"}` and `0.0<=keep_bg_ratio<=1.0`; keep Pocket-HU guard.

### Phase B — separation / mix wiring (bg music preserved)

4. Implement `separate_background` for real (advisor blocking): currently a stub that always raises even with dep present (`stages.py:28-35`). Implement via `audio_separator.separator.Separator(output_dir, model_file="Kim_Vocal_2.onnx")`: `separator.load_model()` + `separate(vocal)` → `(vocals_wav, instrumental_wav)`; normalize return to `(vocal_path, bg_path|None)`; missing-dep and missing-model errors stay explicit RuntimeErrors (no silent fallback). Unit-test with mocked Separator (no 300 MB download in CI).
5. Fix `dubbing/pipeline.py` `run()` (clarified diagnosis: `video.mux_video` mapping `1:a` is by design — `dubbing/video.py:26-28` — the bug is `pipeline.py:91` always passing `bg=None`):
   - `vocal, bg = separate_background(wav, work_dir, job.separation_enabled)` → STT on `vocal`, `mix_with_bg(timeline, bg, job.keep_bg_ratio, …)` (bg preserved at low volume instead of dropped).
   - Pass `job.whisper_model` + `whisper_lang(job.source_lang)` into transcribe; pass through mapped NLLB codes into translate. Log vocal/bg provenance + segment counts. Separation stays opt-in (CPU 10–50×); default path cost unchanged.
6. Fix `dubbing/ui_wizard.py`: pass `separation_enabled`, `whisper_model`, `keep_bg_ratio`, `source_lang="en"` into `DubJob`; persist them in settings on close. No `app.py` changes.

### Phase C — quality automation (fast future testing)

7. New logic lives in importable `dubbing/quality.py` (covered by pytest); `scripts/` stay thin CLI wrappers under existing `if __name__ == "__main__":` coverage exclusion (so `cov≥85` pre-push gate stays green — `pyproject.toml:6`):
   - `scripts/dub_video.py`: CLI driving `DubPipeline` + app Piper TTS (reuses wizard synth pattern, no duplication of engine logic — imports `select_engine` from `app`).
   - `scripts/check_dub_quality.py` (= `dubbing/quality.check()`): gates — SRT exists + ≥1 seg, no empty translations, no repeated-hallucination n-grams, HU spellcheck unknown-word rate reported (hard-fail only when dict present, else warn — explicitly NOT silently green), dubbed duration within ±25% of source span, timeline peak above silence floor, overflow-rate ≤20%. Exit non-zero on fail, prints JSON summary.
   - `scripts/e2e_dub_music.py`: synth EN speech over ffmpeg sine-bed → comparative gate (VAD-on must yield FEWER segments than VAD-off on same clip, and zero segments fully inside music-only span ±1 s) — calibrated comparison, not flaky absolute zero.
8. Tests (pytest, no network) — closing advisor gaps:
   - pipeline: separation wiring (fake separate returns bg → assert `mix_with_bg` received non-None bg; existing full-mock currently stubs it out), NLLB/whisper mappers both directions + passthrough.
   - stages: transcribe passes language+VAD+condition flags (mock WhisperModel, incl. old-version fallback), translate sets `src_lang` + mapped BOS id, empty-seg skip, `separate_background` mocked-Separator success + missing-dep error path.
   - config: new-field defaults + `validate()` rejects bad model/ratio.
   - video: mux with bg-mixed audio arg order (`-map 0:v -map 1:a`), overwrite-refusal already covered (`tests/test_dubbing_video.py:8`).
   - wizard: `DubJob` persistence round-trip (separation/whisper/ratio survive settings save/load).
9. Real-video verification (manual, recorded):
   - Run `scripts/dub_video.py` on user MP4 (full 238 s) with Piper HU Anna + VAD + mapped NLLB; run `check_dub_quality.py`; listen-check first 3 segs + music-bed presence (FFT energy during former music-only span); paste SRT head + quality JSON into plan done notes.
   - Success bar: ≥80% of speech segs intelligible HU (spot-check), zero segs fully inside music-only spans, HU spellcheck unknown-word rate <20% (when dict present), dubbed mp4 has audible HU speech + faint bg music, SRT readable.

## Risks / Reversibility

- Blast radius: `dubbing/` only + 2 new scripts; `app.py` untouched (wizard imports lazily). No DB, no network, no secrets.
- Heavy deps (faster-whisper, NLLB 2.5 GB, audio-separator 300 MB) stay lazy/optional; separation remains opt-in (CPU 10–50×) so default path cost unchanged.
- Rollback: single branch `fix/hu-dub-quality`; revert merge commit restores old pipeline. No migrations.
- Destructive actions: none (unique_output timestamps, never overwrites user video).

## Test plan

- ` .venv/bin/python -m pytest` (full, must pass; pre-push cov ≥85).
- `.venv/bin/ruff check app.py tests/ dubbing/ scripts/dub_video.py scripts/check_dub_quality.py`.
- `git diff --check`.
- New: `.venv/bin/python scripts/check_dub_quality.py --work <dub workdir>` on real dub output (exit 0).
- New: `.venv/bin/python scripts/e2e_dub_music.py` (or extended clip e2e) green.
- Manual: dub user MP4 → mp4 plays HU speech + bg music, SRT readable.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: hermetic stage tests stay green and new wiring is covered — tests/test_dubbing_stages.py:1, tests/test_dubbing_pipeline.py:45, tests/test_dubbing_quality_fix.py:1, e2e smoke scripts/e2e_dub_clip.py:1, mux overwrite-refusal tests/test_dubbing_video.py:8, thin-script coverage exclusion pyproject.toml:6.
- [x] Reused patterns / grounding: pipeline injectable-stage pattern reused, no new abstraction — dubbing/pipeline.py:36; capability registry untouched — app.py:2129; mux mapping by design untouched, fix is bg wiring — dubbing/video.py:26; wizard job-runner reused — dubbing/ui_wizard.py:511; lazy optional-dep pattern reused — dubbing/stages.py:38, dubbing/__init__.py:123.
- [x] Security / privacy: all local, no new network fetch beyond existing user-confirmed model downloads, no secrets — dubbing/stages.py:38, dubbing/__init__.py:123.

```json
{ "total": 94, "axes": { "grounding": 29, "structure": 15, "concreteness": 19, "risk": 14, "tests": 9, "scope": 8 }, "kept_base": 0, "rationale": "revision addresses advisor: real separator impl, two-way lang mappers, mux diagnosis corrected, HU overflow strategy, comparative music e2e, coverage-safe script layout; scope loses 2 for single-branch 3-phase breadth (accepted: user asked for fix+automation together)" }
