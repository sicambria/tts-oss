# PLAN: UI — best defaults, simpler panel, progress + open buttons

Type: IMPROVEMENT
Status: draft
Date: 2026-11-23
Trigger: UI defaults produce bad dubs: separation off (no music), phase-1b off (video refused), engine mirrors TTS panel (Piper instead of clone), separator one-click pollutes repo venv (numpy>=2 breaks Piper/gruut), no progress/ETA, no open-file.

## Summary

RCA: wizard fallbacks hardcode False (ignoring DEFAULT), phase-1b is a dev gate leaking into UI, engine default follows the TTS panel, clone ref never auto-derived, dep panel offers repo-venv audio-separator install (breaks the numpy 1.26.4 pin — lived once already).
Fix: separation default ON (+auto-install isolated env on job start), phase-1b checkbox removed (always allow video), engine default XTTS v2, auto clone-ref from input, separator removed from pip specs + requirements-dubbing.txt points at setup script, determinate progress (synth i/N) + ETA in UI and CLI prints, Open-file/Folder buttons on completion, pure dub_defaults() helper for tests.

## Steps

1. config: separation_enabled default True.
2. stages: +clip_wav(src,start,len,out) helper (shared by wizard + dub_video).
3. ui_wizard: remove phase-1b checkbox (allow_video=True always for video); engine default XTTS v2; separation relabel "Keep original music (recommended)" default on; bg sliders stay; lazy auto clone-ref (stem 30 s, else intro) overriding panel speaker wav; auto-install separator env when missing (logged); progressbar + ETA via pipeline progress; Open-file/Folder buttons enabled on success (cross-platform opener); pure dub_defaults(settings)->dict used for all fallbacks.
4. __init__.py: separator dep pip="" + setup-script hint; engine-aware TTS item (pip TTS==0.22.0) when XTTS selected; _refresh_deps passes engine; engine combo refreshes deps.
5. requirements-dubbing.txt: drop audio-separator line -> setup script note.
6. pipeline: progress callback (extract/sep/stt/mt/synth i-N/timeline/mix/mux with %); default None.
7. dub_video: print [%] lines via progress.
8. Tests: dub_defaults, pip specs exclude audio-separator (regression!), progress monotonic full mocked run, clip_wav real-ffmpeg, wizard persistence keys incl. new ones.
9. Verify: full gates; manual wizard open (Tk present? try) else code-review UI diff.

## Risks / Reversibility

- Blast radius: wizard + dep metadata + pipeline progress kwarg (default None, old callers fine). Rollback: revert merge.
- Auto-install downloads ~1GB on first separated dub: logged line-by-line, worker thread, user already opted into separation by default-on... first-run surprise mitigated by explicit log + status text. No sudo, isolated venv only.

## Test plan

- .venv/bin/python -m pytest (full).
- .venv/bin/ruff check app.py tests/ dubbing/ scripts/dub_video.py scripts/check_dub_quality.py scripts/e2e_dub_music.py.
- git diff --check.
- Headless-safe: no Tk instantiation in tests (pure helpers only).

## Standards & Guardrails Evidence

- [x] Tests / shift-left: defaults/specs/progress/clip tests, no Tk in tests — tests/test_dubbing_quality_fix.py:1, tests/test_dubbing_video.py:8.
- [x] Reused patterns / grounding: injectable stages, lazy deps — dubbing/pipeline.py:36, dubbing/stages.py:38; wizard job-runner — dubbing/ui_wizard.py:511.
- [x] Security / privacy: local only, isolated venv auto-install (no sudo, user cache dir) — scripts/setup_separator_env.sh:1.

```json
{ "total": 94, "axes": { "grounding": 29, "structure": 15, "concreteness": 19, "risk": 14, "tests": 9, "scope": 8 }, "kept_base": 0, "rationale": "RCA names each bad default + trap; scope loses 2 for UI+deps+progress in one branch (single user report)" }
```
