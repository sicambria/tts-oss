# PLAN: BUG — burn-in mux shipped the ORIGINAL audio (dub "still English")

Type: BUG
Status: draft
Date: 2026-11-23
Trigger: user played the delivered v3 mp4: audio still English. Work-dir gates were all green.

## Summary

RCA (synthetic repro, proven): `mux_video` burn-in path had no `-map`, so ffmpeg's automatic stream selection kept input 0's original audio and dropped the dub wav (output FFT peak 440 Hz = original, not 880 Hz dub). The soft-sub path always had explicit maps and was correct. No work-dir gate looked at the DELIVERABLE — check_dub_quality validated only intermediates.

## Steps

1. dubbing/video.py: explicit `-map 0:v:0 -map 1:a:0` on burn path (comment marks them load-bearing); tighten soft path to `:0` selectors.
2. dubbing/quality.py: `mux_audit(output, mixed)` — extract deliverable audio, Pearson correlation vs dub mix, pass >=0.90, fail closed on error.
3. scripts/dub_video.py: post-run mux audit; exit 1 and "do not ship" on failure.
4. Tests: mocked cmd-map assertions (both paths), real-ffmpeg integration repro (440/880, both paths, audit ok), negative audit test (wrong track fails). 595 passed.
5. Verify: rebuild full user dub (separation + XTTS + burn-in); gate incl. mux audit on the mp4; spot SRT; merge.

## Risks / Reversibility

- Blast radius: dubbing/video.py maps only, quality additive, script exit-code on audit fail. No app.py changes. Rollback: revert single merge.
- Correlation threshold 0.90: correct mux scores ~0.99 (codec only); wrong track scores low (shared music bed cannot reach 0.9 against a different voice track — covered by the negative test).

## Test plan

- .venv/bin/python -m pytest (full, must pass).
- .venv/bin/ruff check app.py tests/ dubbing/ scripts/dub_video.py scripts/check_dub_quality.py scripts/e2e_dub_music.py.
- git diff --check.
- Synthetic 440/880 repro peaks 880 after fix.
- Full user dub + scripts/check_dub_quality.py + mux audit on the mp4.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: mocked map assertions + real-ffmpeg integration repro + negative audit — tests/test_dubbing_video.py:8, scripts/e2e_dub_music.py:1.
- [x] Reused patterns / grounding: mux helper stays the single mux point, no new abstraction — dubbing/video.py:13; lazy optional-dep pattern — dubbing/stages.py:38.
- [x] Security / privacy: all local, no new fetches, no secrets — dubbing/stages.py:38, dubbing/__init__.py:123.

```json
{ "total": 96, "axes": { "grounding": 29, "structure": 15, "concreteness": 20, "risk": 15, "tests": 9, "scope": 8 }, "kept_base": 0, "rationale": "root cause proven with synthetic repro before fix; scope loses 2 for bundling audit hardening with the one-line map fix (user explicitly demanded E2E that catches this class)" }
```
