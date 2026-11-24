# FEATURE+RCA: Dubbing Studio burn-in fix + full settings + Extra options + icons

**Type:** FEATURE
**Date:** 2026-11-24
**Branch:** `kaizen/dubbing-settings-ui` (worktree, off `main`)
**Status:** Planned

## Problem

1. **RCA — burn-in checkbox greyed out with deps all OK** (`dubbing/ui_wizard.py:489-497`).
   `_refresh()` enables `burn_btn` only when `input is video AND has_libass()`.
   Three defects combine:
   - `input_path` has no `trace_add` (`dubbing/ui_wizard.py:434` traces only `engine`); only `_browse()` calls `_refresh()` (`dubbing/ui_wizard.py:504-506`). Typing/pasting a video path into the Entry never re-evaluates → stays disabled.
   - `_build_ui()` ends with `_refresh()` (`dubbing/ui_wizard.py:487`) while input is still `""` → `ok=False` → `burn_in.set(False)`, wiping the stored `True` before the user picks a file.
   - `has_libass()` caches globally (`dubbing/__init__.py:84-115`, `_libass_cache`) and is never invalidated, so Re-check / post-install ffmpeg changes return a stale `False` while the dep row (same function) agrees with the stale value.
2. **Missing configs** (audited 2026-11-24): `whisper_model` (no widget, `_start` reads stored only, `dubbing/ui_wizard.py:531`), `audio_output_format` / `video_output_format` (never passed to `DubJob`, `dubbing/ui_wizard.py:524-534`), voice+speed silently pulled from the main TTS panel (`dubbing/ui_wizard.py:591-644`), `output_folder`/`burn_in`/formats not persisted in `_on_close` (`dubbing/ui_wizard.py:794-805`).
3. **No subtitle styling**: `build_burn_filter()` is a bare `subtitles=` filter (`dubbing/subtitles.py:67-68`); font size / color / subtitle track not configurable.
4. **Defaults drift**: `app.py:1717-1727` vs `dubbing/config.py:10-22` vs `dub_defaults()` (`dubbing/ui_wizard.py:59-70`) disagree on engine/separation/burn/levels.

## Design

1. **RCA fix (keep `_refresh()` shape, fix triggers + intent):**
   - `input_path.trace_add("write", ...)` → `_refresh()` so typed/pasted paths re-evaluate.
   - Don't clear `burn_in` when input is empty/unknown; only force `False` for a *known audio* input. Keep widget disabled with an explanatory tooltip/status line stating the reason (no input / audio input / libass missing).
   - Add `reset_libass_cache()` in `dubbing/__init__.py`, call it from `_refresh_deps()` / Re-check before probing. Note: a reset forces the ~1s functional probe (`dubbing/__init__.py:97-115`, temp-clip encode) — run it on the existing Re-check path only (user-initiated), never per keystroke; `_refresh()` itself uses the cached value.
   - Trigger paths fixed (all three): `_build_ui()` end (`dubbing/ui_wizard.py:487`), `_browse()` (`dubbing/ui_wizard.py:504-506`), and `_refresh_deps()` → `_refresh()` (`dubbing/ui_wizard.py:251`) reached from `__init__` (`dubbing/ui_wizard.py:155`) and the `engine` trace (`dubbing/ui_wizard.py:434`).
2. **Single settings source:** `dubbing/config.py:10-22` becomes canonical; `app.py:1717-1727`
   does `from dubbing.config import DEFAULT_DUBBING_SETTINGS` at top level (cycle-free:
   `dubbing/config.py:8` imports only `SUPPORTED_INPUT_EXTS` from the lightweight
   `dubbing/__init__.py`, which never imports `app`; `app.py` currently has zero top-level
   `dubbing` imports — only lazy imports inside methods at `app.py:6066,6076` — and the
   wizard's `app` imports stay lazy inside functions at `dubbing/ui_wizard.py:599-604,807`).
   Import from `dubbing.config`, never from the package root.
   `dub_defaults()` (`dubbing/ui_wizard.py:37-70`) keeps best defaults (source `en`,
   target `hu`, engine `XTTS v2`, separation on, burn on, duck `0.5/1.0`, whisper `small`,
   audio `mp3`, video `mp4`) and round-trips all keys including new subtitle keys.
   Acknowledged behavior change: `normalize_app_settings` (`app.py:1829-1845`,
   `{**defaults, **section}`) only fills missing keys, so existing stored users are
   unaffected, but **new/default users flip** from the stale `app.py` values
   (`burn_in=False`, `keep_bg_ratio=0.2`, `separation_enabled=False`) to the intended
   best defaults (`True`/`0.5`/`True`). Justification: the `app.py` values contradict the
   tested contract (`tests/test_dubbing_quality_fix.py:514`) and the wizard docstring
   (`dubbing/ui_wizard.py:40-43`); the flip is the bug fix, called out in `KNOWN_ISSUES.md`.
3. **New `DubJob`/settings keys** with validation spelled out in `DubJob.validate`
   (`dubbing/config.py:62-91`): `subtitle_track` (`translated`/`source`, default
   `translated`), `subtitle_font_size` (int 12–32, default 20),
   `subtitle_font_color` (ASS `&HAABBGGRR`, validated by regex, default `&H00FFFFFF`),
   `subtitle_outline` (0–4, default 2). NO `both` option: a both-tracks soft output would
   require a second subtitle stream / merged SRT, contradicting the mux contract — out of
   scope. `subtitle_track` applies to the **burn path only**; the soft-sub path always muxes
   the translated track + writes the `dub.srt` sidecar, documented in the UI label.
4. **`force_style` construction (exact spec):** new pure helper
   `build_subtitle_style(size, color, outline) -> str` in `dubbing/subtitles.py` validates
   ranges/regex and returns e.g. `FontSize=20,PrimaryColour=&H00FFFFFF,Outline=2`.
   `build_burn_filter(srt, style=None)` emits a SINGLE `-vf` arg
   `subtitles=<escaped>:force_style='<style>'` where `<escaped>` uses the existing
   `escape_sub_path` quoting (`dubbing/subtitles.py:62-64`, same module as
   `build_burn_filter` at `dubbing/subtitles.py:67-68`) and the style block is
   single-quoted (no commas/colons inside values by construction — validated).
   No new quoting helper is created. Soft-sub
   styling stays player-side (SRT/`mov_text` carry no style channel). `mux_video()`
   (`dubbing/video.py:13-33`) takes an optional `style` param passed to the burn branch
   only; soft branch and stream maps (`dubbing/video.py:25-33`) untouched.
5. **Extra options window:** main wizard keeps file/lang/engine/music/output/Run; new `Extra options…` button opens a `Toplevel` with whisper model, audio/video format, subtitle track + style, NLLB model display (env `DUB_NLLB_MODEL`, `dubbing/stages.py:18-19`, read-only + override hint). No new third-party deps. Headless/coverage rule: Toplevel code stays thin (widget wiring only); ALL logic lives in pure helpers (`dub_defaults`, `build_subtitle_style`, validation) covered by tests; `_build_ui` keeps its `# pragma: no cover` (`dubbing/ui_wizard.py:382`).
6. **Persistence:** `_start()` passes all settings into `DubJob`; `_on_close()` persists *every* dubbing key (incl. `burn_in`, `whisper_model`, formats, subtitle keys, output folder) via `save_app_settings` (`app.py:1868`); wizard loads via `dub_defaults()` at open.
7. **Icons (minimal):** reuse `make_playback_icon()` (`app.py:288-339`) with `compound="left"` on the primary action buttons only (Generate/Stop/Browse/Close/Open) — no full-button icon pass. Icon creation guarded with `try/except` (headless-safe, falls back to text-only); reuse cached app icons where available. No image assets, Xft-safe per `AGENTS.md:50-53`.

## Steps

1. Create worktree `kaizen/dubbing-settings-ui` off `main`; confirm clean.
2. RCA fix: trace on `input_path`, intent-preserving `_refresh()`, `reset_libass_cache()` + call sites.
3. Unify defaults (`app.py` imports `dubbing/config.py`); extend `DEFAULT_DUBBING_SETTINGS` + `DubJob` + `validate()` with subtitle keys; extend `dub_defaults()` round-trip.
4. `build_burn_filter(srt, style=None)` + `mux_video()` pass-through; `soft_sub_mux_args()` untouched.
5. Extra-options `Toplevel`; wire all settings into `_start()` → `DubJob`; persist all in `_on_close()`.
6. Icons on primary action buttons only (Generate/Stop/Browse/Close/Open) via `make_playback_icon`.
7. Tests + verify contract; docs (`README.md` dubbing section, `KNOWN_ISSUES.md` entry for the trace/cache RCA); move plan to `docs/plans/done`.

## Risks and rollback

- Blast radius: `dubbing/` + `app.py` defaults import + tests. Main TTS synthesis untouched; `_app_synthesizer` voice sourcing unchanged (now labeled, not rerouted).
- libass `force_style` syntax varies by ffmpeg build — burn path validates by reusing the existing `has_libass()` probe pattern; failure falls back to unstyled burn with a logged note, never a silent wrong-audio mux (maps in `dubbing/video.py:25-33` untouched).
- Rollback: revert worktree merge commit (`git revert`), settings JSON stays forward-compatible (unknown keys ignored by `dub_defaults()`).

## Test plan

- New `tests/test_dubbing_settings_ui.py`: trace re-enables burn on typed video path; empty input preserves `burn_in=True`; audio input forces `False`; cache reset flips stale `False→True` (monkeypatched probe); `dub_defaults` round-trips every key incl. subtitle keys; `build_subtitle_style` unit tests (defaults, clamping/reject of bad size/color/outline) + `build_burn_filter` with an adversarial path (spaces/colons/quotes) asserting a single `-vf` arg with intact `force_style`; `_on_close` persists full key set (persist pattern as in `tests/test_language_learning_wizard.py:152` `test_save_preset_updates_app_and_persists`).
- Full verify: `.venv/bin/python -m pytest`, `.venv/bin/ruff check app.py tests/`, `git diff --check`, `node .harness/scripts/verify.mjs`. Coverage gate ≥85 holds (new code covered by new tests).
- Manual: open wizard with no input (burn disabled + reason shown, intent kept), type video path (enables), audio path (disabled + forced off), Re-check after ffmpeg change.

## Standards & Guardrails Evidence

- [x] Tests / shift-left: new tests in `tests/test_dubbing_settings_ui.py` (pattern: `tests/test_dubbing_quality_fix.py:514` `test_dub_defaults_best_and_stored`); verify via `.harness/config.json:132-137` (`test`/`lint`/`build`).
- [x] Reused patterns / grounding: reuses `make_playback_icon` at `app.py:288`, `save_app_settings` at `app.py:1868`, `_refresh_deps` probe pattern at `dubbing/ui_wizard.py:211-253`, mux maps at `dubbing/video.py:25-33`; no new deps or assets.
- [x] Security: N/A — no secrets/network/auth; settings are local JSON via existing `load_app_settings`/`save_app_settings` (`app.py:1730-1745`); subprocess calls unchanged (`dubbing/video.py:34`, `dubbing/stages.py:74-78`).
