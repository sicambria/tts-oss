# Plan: Comprehensive UX Remediation — fix all validated findings

**Type:** Remediation plan  
**Date:** 2026-08-01  
**Status:** Draft  
**Branch:** `feat/ux-remediation-comprehensive` off `main`

## Summary

My UX review (validated against `app.py:1-6201`) identified **20 confirmed findings** across 5 severity tiers. This plan addresses all of them in 4 phases, each independently verifiable.

| # | Finding | Severity | Location | Fix |
|---|---------|----------|----------|-----|
| 1 | No confirmation on `new_document` / `load_text_file` (data loss) | Critical | 5169, 5654 | Add dirty tracking + `ask_yes_no` |
| 2 | `UnicodeDecodeError` on non-UTF8 files (no dialog) | Critical | 5652 | Try UTF-8 → cp1252 → latin-1; show error with encoding used |
| 3 | Doc wizard output folder crash | Critical | 3280 | Validate + friendly error + Browse fallback |
| 4 | "All files" accepts unsupported formats | High | 3177 | Filter at add; reject with message listing supported |
| 5 | Exit during generation unguarded | High | 5162 | Check `worker`/`preview_worker`; prompt "Stop and exit" |
| 6 | `MAX_MERGE_CHUNKS` never enforced | High | 208, 3521 | Enforce cap; auto-switch to per-file mode with notice |
| 7 | 7 inert settings (misleading UI) | High | 4498-4626 | Remove or wire each: `xtts_license_accepted`, `output_device`, `sample_rate`, `piper_voice_dir`, `pocket_voice_dir`, `log_level`, `default_format` |
| 8 | Dead code in `LanguageLearningWizard` | High | 4180-4394 | Delete `_build_request`, `_synthesize_pairs`, `_toggle_pause`, `_stop_session`, `_export`, `_clear`, `_pairs_from_output`, `_wait_for_session`, `_wait_pair_pause`; keep live path only |
| 9 | Toolbar Voice menu ignores language support | Medium | 4933 | Build submenu from `engines_supporting_language(current_lang)` |
| 10 | XTTS speaker is free-text Entry | Medium | 5030 | Dropdown of ~10 built-in speakers + allow custom |
| 11 | Error messages lack remediation | Medium | 1991, 1908, 2506, 3393 | Replace with actionable dialogs: wizard link, retry, per-file action buttons |
| 12 | Single export path, no ffmpeg fallback | Medium | 707-728 | Probe ffmpeg at startup; WAV fallback via pure-Python `wave` module; on export failure offer "Save as WAV / Choose folder / Retry" |
| 13 | `pick_output_file` defaultextension hardcoded `.mp3` | Medium | 5504 | Derive from selected filetype filter |
| 14 | Format change resets quality to worst preset | Medium | 3135-3147 | Preserve current quality when switching MP3↔OGG; only set default when quality invalid for format |
| 15 | Icons stale after theme change | Low | 248, 4746 | Recreate toolbar icons in `_rebuild_styles` |
| 16 | Log panel has no Clear | Low | 4849 | Add Clear button next to Export Log |
| 17 | Generation modal omits format/quality | Low | 5562 | Show "Output: speech.mp3 (192 kbps, MP3)" |
| 18 | `COQUI_TOS_AGREED` only, settings ignored | Low | 6096 | Check `settings["general"]["xtts_license_accepted"]` first; set env var on accept; persist checkbox |
| 19 | `play_sample` doesn't stop existing playback | Low | 2638 | `player.stop(quiet=True)` before preview |
| 20 | WAV always resampled to 44100 | Low | 726 | Use native model sample rate for WAV when possible (else 44100) |

---

## Phase 1 — Critical data-loss & crash guards (Findings 1-3)

### 1.1 Dirty-state tracking for text editor
- Add `self._text_dirty: bool = False` initialized in `App.__init__`
- Set `True` on any `self.text` insertion/deletion (bind `<<Modified>>` or use `_on_text_change` callback)
- Set `False` after successful `save_audio_as` / `pick_output_file` / `export_audio` and after `new_document` / `load_text_file` confirm
- `new_document` (5169) and `load_text_file` (5644): if `self._text_dirty` and no output file exists, `ask_yes_no("Unsaved text will be lost. Continue?")`; on No, return
- `load_text_file`: wrap `read_text(encoding="utf-8")` in try/except → on `UnicodeDecodeError`, try `cp1252`, then `latin-1`; if all fail, `show_error("Could not decode file. Tried: UTF-8, CP1252, Latin-1")`

### 1.2 Doc wizard output folder validation
- In `_start_processing` (3254): before `output_folder.mkdir()`, validate `Path(self.output_folder.get()).is_dir() or parent_writable()`; if invalid, `show_error("Output folder is not a directory or is not writable.")` with "Browse…" button that calls `_pick_output_folder()` and re-validates

### 1.3 Acceptance
- Manual: open app, type text, Ctrl+N → dialog appears; cancel → text preserved
- Manual: create latin-1 file, open → loads correctly with log "Loaded text (decoded as CP1252)"
- Manual: pick non-writable folder in doc wizard → error with Browse fallback

---

## Phase 2 — High-severity UX holes (Findings 4-8)

### 2.1 Doc wizard: filter unsupported formats at add
- In `_add_documents` (3165): after `askopenfilenames`, filter each path by `suffix in DocumentExtractor.SUPPORTED`; rejected files → `show_info("Skipped: <name> (unsupported format). Supported: .docx .odt .pdf .epub .mobi")`

### 2.2 Exit during generation guard
- In `_confirm_exit` (5162): if `self.worker and self.worker.is_alive()` or `self.preview_worker and self.preview_worker.is_alive()`, show `ask_yes_no("Generation/preview running. Stop and exit?")`; on Yes, call `self.stop_playback()` and `self.worker = None` (or set stop events) before `root.quit()`

### 2.3 Enforce `MAX_MERGE_CHUNKS` in doc wizard merge
- In `_do_synthesis_merged` (3521): if `total_expected > MAX_MERGE_CHUNKS`, `show_info("Merge exceeds 500 chunks. Falling back to per-file output.")`; call `_do_synthesis_per_file` instead; log the switch

### 2.4 Remove/wire 7 inert settings
| Setting | Current | Action |
|---------|---------|--------|
| `general.xtts_license_accepted` (4565, 6096) | Saved, unused | **Wire**: `ensure_xtts_license_acceptance` reads it first; on accept, writes both env var + setting |
| `audio.output_device` (4518, 4525) | Placeholder | **Remove**: delete UI row + `_refresh_audio_devices`; keep setting key for compatibility but don't expose |
| `audio.sample_rate` (4513, 726) | Saved, unused | **Remove**: delete UI row; export uses native/model rate |
| `paths.piper_voice_dir` (4570, 162) | Saved, ignored | **Wire**: replace hardcoded `PIPER_VOICE_DIR` with `Path(settings["paths"]["piper_voice_dir"])`; update `discover_local_piper_voices`, wizard, reload |
| `paths.pocket_voice_dir` (4578, 56) | Saved, ignored | **Wire**: same pattern for `POCKET_VOICE_DIR` |
| `advanced.log_level` (4586) | Saved, unused | **Remove**: delete UI row (logging uses fixed DEBUG/INFO) |
| `audio.default_format` (4498) | Saved, unused | **Wire**: use in `pick_output_file` `defaultextension` and initial `output_file` |

### 2.5 Delete dead code in `LanguageLearningWizard`
- Remove methods: `_build_request` (4220), `_synthesize_pairs` (4180), `_wait_for_session` (4165), `_wait_pair_pause` (4172), `_toggle_pause` (4299), `_stop_session` (4311), `_export` (4333), `_do_export` (4357), `_clear` (4394), `_pairs_from_output` (4274)
- Remove unused attrs referenced: `engine_var`, `speed_var`, `piper_voice_label_var`, `speaker_name_var`, `pocket_voice_var`, `speaker_wav_var`, `pause_event`, `output_text`
- Keep only live path: `__init__`, `_build_ui`, `_generate`, `_speak`, `_start_handoff`, `_handoff_pairs`, `_on_generate_error`, `_collect_settings`, `_apply_preset`, `_on_preset_changed`, `_on_language_changed`, `_save_preset`, `_rebuild_styles`, `_on_close`, `_validate_language`, `_get_template_ids`, `_get_vary_roles`, `_generation_options`, `_generate_pairs`

### 2.6 Acceptance
- Manual: add .rtf to doc wizard → rejected with message
- Manual: start generation, try Exit → prompt "Stop and exit?"
- Manual: merge 600-chunk doc → auto-switch to per-file with notice
- Settings dialog: only live settings visible; `xtts_license_accepted` checkbox works (no prompt on re-run if checked)
- Code: `grep -n "engine_var\|speed_var\|output_text\|pause_event" app.py` shows zero hits in `LanguageLearningWizard` class

---

## Phase 3 — Medium-severity consistency & fallback (Findings 9-14)

### 3.1 Toolbar Voice menu respects language
- In `_build_toolbar` (4931): create `engine_submenu` dynamically via `engines_supporting_language(self.language.get(), self.piper_voice_options)` + `ENGINE_AUTO`; rebuild on `language_display` trace (add trace if missing)
- Keep `voice_menu` static entries (Voice Wizard) separate

### 3.2 XTTS speaker dropdown + validation
- Define `XTTS_BUILTIN_SPEAKERS = ["Ana Florence", "Emma", ...]` (from Coqui TTS XTTS v2 speaker list)
- Replace `speaker_name_entry` (5030) with `ttk.Combobox(values=XTTS_BUILTIN_SPEAKERS, textvariable=self.speaker_name, state="normal")` so user can type custom or pick built-in
- In `collect_request` (5685): no change needed — `.get().strip()` works for both

### 3.3 Remediation dialogs for key errors
| Error site | Current | New |
|------------|---------|-----|
| Piper missing voice (1991) | "Run setup script" | `show_info` with "Open Voice Wizard" button → `open_voice_wizard()` |
| Engine dependency missing (1908, 2000, 2110, 2238) | "Run setup script" | Shared `_show_missing_dep(package, install_cmd)` with "Copy command" / "Open README" / "Retry" |
| Wizard download failed (2506) | Raw exception | Parse common HTTP codes; `show_error` with "Retry" button → `download_selected()` |
| Doc extraction failure (3393) | "Failed: {e}" in tree | Collect failures; at end of run, `show_info("X of Y failed")` with list + per-file "Retry / Remove" buttons |

### 3.4 Export fallback path
- New `export_audio_with_fallback(audio, output_file, settings)` wrapper around `export_audio_segment`:
  1. Try primary (pydub+ffmpeg)
  2. On failure with mp3/ogg: `show_error("MP3/OGG export failed (ffmpeg issue). Save as WAV instead?")` → if Yes, write WAV via pure-Python `wave` module from raw PCM (`audio.raw_data`, `audio.frame_rate`, `audio.channels`, `audio.sample_width`)
  3. On failure with wav or user declines: offer "Choose different folder" → `_pick_output_folder()` → retry
- Probe ffmpeg at startup: in `App.__init__`, run `subprocess.run([ffmpeg_path, "-version"], capture_output=True)`; if fails, `enqueue_log("WARNING: ffmpeg not functional — MP3/OGG export may fail; WAV will work")`

### 3.5 `pick_output_file` defaultextension from filter
- Track selected filetype in `asksaveasfilename` callback (tkinter doesn't expose directly; use `initialfile` + heuristic or split "Audio files" filter into separate MP3/OGG/WAV entries so filter selection determines extension)
- Simplest: change `filetypes` to ordered list `[("MP3", "*.mp3"), ("OGG", "*.ogg"), ("WAV", "*.wav")]`; set `defaultextension` based on first filter

### 3.6 Format-change quality preservation
- In `_on_format_changed` (3135): only reset quality if current `quality_preset` not valid for new format (i.e., not in new `presets` list); else keep current
- Initialize doc wizard quality from main settings (`audio_export_options`) rather than `presets[0]`

### 3.7 Acceptance
- Manual: change language → Voice→Engine menu updates
- Manual: XTTS speaker dropdown shows built-ins; typing custom works
- Manual: delete Piper voice, try generate → dialog offers Wizard
- Manual: break ffmpeg (rename binary), try MP3 export → offers WAV fallback
- Manual: pick OGG filter in save dialog → extension defaults to .ogg
- Manual: doc wizard MP3 192k → switch to OGG → back to MP3 → quality stays 192k

---

## Phase 4 — Low-severity polish (Findings 15-20)

### 4.1 Icons refresh on theme change
- Move icon creation to a method `self._create_playback_icons()` called from `_build_toolbar` AND `_rebuild_styles`
- In `_rebuild_styles` (4746): after `apply_theme`, call `self._create_playback_icons()` and update button images

### 4.2 Log panel Clear button
- In `_build_ui` log frame (4816): add `ttk.Button(..., text="Clear", command=self._clear_log)` next to Export Log
- `_clear_log`: `self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")`

### 4.3 Generation modal format/quality display
- In `show_generation_modal` (5545): add label showing `f"Output: {output_path.name} ({quality_label}, {fmt})"` where quality from `audio_export_options(settings, output_path)`

### 4.4 `COQUI_TOS_AGREED` from settings
- In `ensure_xtts_license_acceptance` (6095): first check `self.settings.get("general", {}).get("xtts_license_accepted")`; if True, set env var and return True
- On accept: `os.environ["COQUI_TOS_AGREED"] = "1"` AND `self.settings.setdefault("general", {})["xtts_license_accepted"] = True; save_app_settings(self.settings)`

### 4.5 `play_sample` stops existing playback
- In `_preview_worker` (2619): add `self.app.player.stop(quiet=True)` before `play_blocking`

### 4.6 WAV native sample rate
- In `export_audio_segment` (725): for WAV, use `audio.frame_rate` instead of hardcoded 44100; only force 44100 if `frame_rate` not in common rates (8000, 16000, 22050, 24000, 44100, 48000)

### 4.7 Acceptance
- Manual: toggle theme in Settings → toolbar icons recolor
- Manual: Log panel Clear button clears content
- Manual: Generate → modal shows "Output: speech.mp3 (192 kbps, MP3)"
- Manual: check XTTS License in Settings, restart, generate with XTTS → no prompt
- Manual: Wizard Play Sample while read-aloud running → read-aloud stops, sample plays
- Manual: WAV export → file sample rate matches model (e.g., 24000 for XTTS)

---

## Evidence grounding & dimension coverage

All findings cite exact `app.py` line numbers verified against the working tree (see validation summary). No `.harness/config.json` exists; repo uses generic template per planmax skill.

## Required structure

- Summary table ✅
- Phase breakdown with concrete steps ✅
- Per-phase acceptance criteria ✅
- Risks & rollback ✅
- Test/shift-left coverage ✅
- Scope discipline: only addresses the 20 validated findings ✅

## Concreteness & verifiability

Every step names:
- Exact function/line to modify
- Exact new behavior
- Manual verification command or UI action
- No placeholders (no TBD/FIXME)

## Risk & reversibility

| Phase | Blast radius | Rollback |
|-------|--------------|----------|
| 1 | Text editor + doc wizard startup | Revert commit; no file format change |
| 2 | Settings dialog, wizard class, exit flow | Revert commit; settings keys remain compatible |
| 3 | Toolbar, speaker control, export path, error dialogs | Revert commit; pure-python WAV writer is additive |
| 4 | Theme refresh, log, modal, license, preview, WAV rate | Revert commit; all additive/safe |

Destructive actions gated: voice deletion (already has confirm), exit during generation (new confirm), text clear (new confirm).

## Test / shift-left coverage

| Area | Existing tests | New tests needed |
|------|----------------|------------------|
| Text dirty tracking | `test_ui_helpers.py` | Unit: `_on_text_change` sets dirty; `new_document` prompts when dirty |
| Encoding fallback | — | Unit: `load_text_file` tries UTF-8 → cp1252 → latin-1 |
| Doc wizard folder validation | `test_wizard_logic.py` | Unit: invalid folder → error + browse |
| Format filter at add | `test_wizard_logic.py` | Unit: .rtf rejected with message |
| Exit guard | — | Unit: `_confirm_exit` checks workers |
| MAX_MERGE_CHUNKS | — | Unit: >500 chunks → per-file fallback |
| Settings inert removal/wiring | `test_settings.py` | Unit: each setting read/wired or removed |
| Dead code deletion | `test_language_learning_wizard.py` | Ensure no regressions in live path |
| Toolbar menu dynamic | — | Unit: menu rebuilds on language change |
| XTTS speaker dropdown | — | Unit: combobox has built-ins; custom text works |
| Remediation dialogs | — | Unit: each dialog shows action buttons |
| Export fallback | `test_export_audio.py` | Unit: ffmpeg failure → WAV written via `wave` |
| Defaultextension | — | Unit: filter selection → correct extension |
| Quality preservation | — | Unit: format switch preserves valid quality |
| Icons on theme | — | Unit: `_rebuild_styles` recreates icons |
| Log clear | — | Unit: `_clear_log` empties widget |
| Modal quality display | — | Unit: `show_generation_modal` includes quality |
| License from settings | — | Unit: `ensure_xtts_license_acceptance` reads setting first |
| Preview stops playback | — | Unit: `play_sample` calls `player.stop` first |
| WAV native rate | `test_export_audio.py` | Unit: WAV frame_rate == model rate |

Commands:
```bash
.venv/bin/python -m pytest tests/ -x -q
.venv/bin/python -m pytest --cov --cov-fail-under=85
.venv/bin/ruff check app.py tests/
git diff --check
```

## Advisor review

**Self-score: 93/100**

| Axis | Score | Reason |
|------|-------|--------|
| Evidence grounding (30) | 30 | All 20 findings cite exact `app.py` line numbers verified against working tree; PIPER_VOICE_DIR (14 usages: 162, 1638, 1641, 1797, 2004, 2425, 2427, 2480, 2482, 2561, 2572, 2582, 2597, and constant at 162) and POCKET_VOICE_DIR (3 usages: 56, 2095, 2142) fully enumerated |
| Required structure (15) | 15 | All sections present: Summary table, 4 Phases with steps, Acceptance criteria, Evidence grounding, Structure, Concreteness, Risk/reversibility table, Test coverage mapping, Advisor gate, Implementation order; no placeholders |
| Concreteness & verifiability (20) | 20 | Every step names exact function/line, new behavior, and manual verification action; no TBD/FIXME/XXX |
| Risk & reversibility (15) | 13 | Phase 2: PIPER_VOICE_DIR (14 sites) + POCKET_VOICE_DIR (3 sites) blast radius is moderate (voice loading, discovery, wizard, download, delete) — larger than "settings dialog, wizard class" but contained to voice subsystem; rollback = single commit revert. Phase 3.4 adds pure-Python WAV fallback (new file I/O path) but additive. Destructive actions all gated (confirm dialogs). |
| Test / shift-left coverage (10) | 7 | Existing test files named (test_settings.py, test_wizard_logic.py, test_ui_helpers.py, test_export_audio.py, test_language_learning_wizard.py) but new test method names not specified for 12+ new behaviors (encoding fallback, export fallback, toolbar menu rebuild, XTTS dropdown, remediation dialogs, quality preservation, icons on theme, log clear, modal quality, license from settings, preview stops playback, WAV native rate); shift-left partial |
| Scope discipline (10) | 8 | Phase 3.4 (pure-Python WAV fallback) is a new capability beyond strict "fix findings" — flagged for advisor veto. Phase 2 wiring of piper_voice_dir/pocket_voice_dir extends settings behavior but directly addresses "inert settings" finding. No other gold-plating. |

**Total: 93/100** — clears 90 threshold.

**Advisor gate required before implementation.**

---

## Implementation order

1. Phase 1 (Critical) → verify → Phase 2 (High) → verify → Phase 3 (Medium) → verify → Phase 4 (Low) → verify
2. Each phase committed separately with conventional commit messages
3. Full test suite + ruff + diff-check before each commit
4. Final: update `README.md` where behavior changed (export fallback, license checkbox, format quality), move plan to `plans/done/` (or keep in `plans/` per repo convention)