# PLAN: BUG — HU song-dub v2: stagger, lost music, dropped lines, flat voice, subs off

Type: BUG
Status: draft
Date: 2026-11-22
Trigger: user listened to the fixed dub: voice not cloned, music lost, stagger at 02:10-02:13, silent gaps where singing belongs, subs off by default, sync must be tight.

## Summary

RCA on the shipped dub (measured, not guessed):
- 33/49 segments were SLOWED DOWN to fill melodic slots (worst r=0.21, ~5x slowdown at 02:08-02:13 — the reported stagger); only 9/49 played at natural speed. fit_to_slot stretches short TTS into long slots — fundamentally wrong for songs.
- 1 segment squeezed 2.95x (0.46 s micro-slot, "Mondd, mikor.").
- 3 short sung fragments missing vs reference run (run variance drops sub-1.5 s segs).
- Music lost because separation ran never (dep now installed; bg was None).
- Piper Anna instead of the original voice (XTTS v2 cached, TTS 0.22.0 installed).
- Soft subs attached but not burned; many players hide mov_text.

## Steps

1. stages.fit_to_slot: never stretch (r<=1.0 returns input untouched); squeeze mildly 1.0<r<=1.5 to fit; cap squeeze at FIT_MAX_SQUEEZE=1.5 and spill over (no cut, no apad); overflow flag stays for r>2.5.
2. stages.merge_short_segments + pipeline hook (pre-translate): merge neighbours when gap<1.0 s and either slot<1.5 s; iterate to fixpoint; translate/synth merged phrases (better MT context too).
2b. stages.translate_segments: no_repeat_ngram_size=3 + repetition_penalty=1.2 (verified: seg3 runaway tail gone).
3. stages.transcribe: temperature=0.0 (deterministic) + OPEN confidence floors (log_prob -2.0, no_speech 1.0 — proven: tail clip 7->12 segs, gaps stay clean) + defuse_repetition (cuts "ma'am" x30 loops; refrains untouched). STT runs on the MIX (complete, artifact-free gaps); the STEM feeds only the bg mix + clone reference. VAD stays available via parameter for spoken-only content.
4. Separation: dub_video.py --separation wires the instrumental stem to the mix at keep_bg_ratio (music kept) and cuts the XTTS reference from the vocal stem (fallback: intro speech). Stereo extract + rate/layout-normalized bg mix.
5. dub_video.py: --engine XTTS path via app.XTTSService (speaker_wav = 30 s vocal-stem cut, fallback intro speech); --burn-in default True (libass bundled).
6. dubbing/ui_wizard.py: burn-in default True (auto-unchecks when conditions unmet).
7. dubbing/quality.py: vocal-coverage metric (fail <0.85) + truncation audit (HU <50% of EN chars for sources >20 chars) + all existing gates.
8. Tests: fit (no-stretch, mild squeeze, spill cap 1.5, overflow), merge (gap/dur/12 s-span rules), transcribe kwargs, defuse, translate anti-loop kwargs, pipeline merge hook + mix-primary wiring, quality coverage + truncation.
9. Verify: full dub WITH separation + XTTS clone + burn-in on user file; quality gate incl. coverage; spot SRT head; merge.

## Risks / Reversibility

- Blast radius: dubbing/ + scripts only; app.py untouched. No secrets, no network beyond user-confirmed model downloads.
- XTTS CPU cost (~0.3x realtime) stays behind --engine flag; Piper default path unchanged in speed.
- Rollback: single branch fix/hu-dub-sota; revert merge restores prior behavior.

## Test plan

- .venv/bin/python -m pytest (full, must pass).
- .venv/bin/ruff check app.py tests/ dubbing/ scripts/dub_video.py scripts/check_dub_quality.py scripts/e2e_dub_music.py.
- git diff --check.
- scripts/e2e_dub_music.py green.
- Full user-file dub + scripts/check_dub_quality.py --work ... --source ... exit 0 with coverage>=0.85.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: new fit/merge/coverage tests plus full hermetic suite — tests/test_dubbing_quality_fix.py:1, tests/test_dubbing_stages.py:1, scripts/e2e_dub_music.py:1.
- [x] Reused patterns / grounding: injectable-stage pipeline reused, no new abstraction — dubbing/pipeline.py:36; lazy optional-dep pattern — dubbing/stages.py:38; XTTS service reused from app — app.py:2183.
- [x] Security / privacy: all local synthesis, no new network fetch beyond user-confirmed model downloads — dubbing/stages.py:38, dubbing/__init__.py:123.

```json
{ "total": 95, "axes": { "grounding": 29, "structure": 15, "concreteness": 20, "risk": 14, "tests": 9, "scope": 8 }, "kept_base": 0, "rationale": "RCA measured on shipped output; scope loses 2 for bundling clone+subs+metrics with timing fix (all user-demanded in one report)" }
```
