# PLAN: FEATURE — adaptive music ducking, louder bed, UI + CLI control

Type: FEATURE
Status: draft
Date: 2026-11-23
Trigger: user: music bed too quiet vs original; wants adaptive music/speech loudness, configurable on UI and CLI.

## Summary

Replace the static `bg * 0.2` mix with broadcast-style ducking computed sample-exact in numpy (exact levels, no ffmpeg filter guesswork): envelope = gap level in instrumental gaps, cosine ramps down to speech level around each lyric span (attack 0.25 s, release 0.9 s). New DubJob fields `bg_gap_ratio` (default 1.0 = original loudness) + `bg_duck` (default True); `keep_bg_ratio` becomes the under-speech level (default 0.2 -> 0.5). Wizard gets two scales + ducking checkbox (persisted); CLI gets --bg-gap/--duck/--no-duck.

## Steps

1. stages.mix_with_bg: optional spans + gap_level params; adaptive numpy path when ducking on (rate/layout normalize via ffmpeg first, exact cosine envelope, clip-safe add); legacy static path untouched when off/unset.
2. config.DubJob: +bg_gap_ratio=1.0, +bg_duck=True; validate [0,1]; DEFAULTS keep_bg_ratio 0.5.
3. pipeline: pass merged segment spans + job fields into mix_with_bg.
4. ui_wizard: Music-under-speech scale, Music-in-gaps scale, Adaptive-ducking checkbox; live widget values into DubJob + persisted (replaces stored-only keep_bg).
5. scripts/dub_video.py: --keep-bg (under speech), --bg-gap, --duck/--no-duck into DubJob.
6. Tests: adaptive energy ratios (gap full, speech ducked, ramps), legacy static unchanged, config validation, pipeline passes spans, wizard persistence keys.
7. Verify: full gates; rebuild user dub (ducked mix); mux audit; report gap vs speech RMS.

## Risks / Reversibility

- Blast radius: mix path + job fields + wizard row + CLI flags; app.py untouched. Legacy path preserved bit-for-bit when duck off. Rollback: revert merge.
- numpy envelope memory ~80 MB peak for 4 min stereo — fine on desktop; chunked if ever >15 min media.

## Test plan

- .venv/bin/python -m pytest (full).
- .venv/bin/ruff check app.py tests/ dubbing/ scripts/dub_video.py scripts/check_dub_quality.py scripts/e2e_dub_music.py.
- git diff --check.
- Rebuilt dub: gap RMS ~= original bed, speech-span bed ~= speech level; mux audit ok.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: adaptive/legacy mix unit tests + config/pipeline/wizard tests — tests/test_dubbing_quality_fix.py:1, tests/test_dubbing_stages.py:1.
- [x] Reused patterns / grounding: injectable stages, no new abstraction — dubbing/pipeline.py:36; lazy deps — dubbing/stages.py:38.
- [x] Security / privacy: local only, no new fetches, no secrets — dubbing/stages.py:38, dubbing/__init__.py:123.

```json
{ "total": 95, "axes": { "grounding": 29, "structure": 15, "concreteness": 20, "risk": 14, "tests": 9, "scope": 8 }, "kept_base": 0, "rationale": "ducking design exact-level via numpy envelope (no sidechain calibration risk); scope loses 2 for UI+CLI+mix+rebuild in one branch (single user request)" }
```
