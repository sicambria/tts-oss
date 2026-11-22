# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
./run.sh          # Linux/macOS
.\run.ps1         # Windows
```

Setup (first time, CPU):
```bash
./setup.sh        # Linux/macOS
.\setup.ps1       # Windows
# CUDA 12.1:
./setup.sh cu121
.\setup.ps1 -TorchChannel cu121
```

The app is a native `tkinter` desktop window — there is no browser UI, no localhost server, and no HTTP endpoint.

## Architecture

Core TTS app lives in `app.py`. Dubbing Studio lives in the `dubbing/` package. `tests/` holds the pytest suite (ruff + coverage-gated hooks).

**Class hierarchy:**

- `SynthesisCoordinator` — top-level engine router. Resolves `Auto` to Piper, XTTS, or Pocket based on language, reference WAV, and installed voices (via `select_engine()`), then delegates to the right service.
- `PiperService` — runs Piper TTS locally. Loads `.onnx` voice models from `voices/piper/`. Caches loaded voices in memory.
- `XTTSService` — loads and runs the Coqui XTTS v2 model (`tts_models/multilingual/multi-dataset/xtts_v2`). Lazy-loaded on first synthesis. Patches `torch.load` to set `weights_only=False` for compatibility.
- `PocketTTSService` — runs the Pocket TTS engine. Voice must come from `POCKET_PREDEFINED_VOICES`.
- `AudioPlayer` — wraps `pygame.mixer` for read-aloud playback with pause/resume/stop.
- `App` — the `Tk` root window. Owns all UI state, spawns synthesis on background threads, routes log messages through a `queue.Queue` flushed by a periodic `root.after` callback.
- `PiperVoiceWizard` — a `Toplevel` dialog for browsing and downloading additional Piper voices from the official catalog.
- `DocumentToAudioWizard`, `LanguageLearningWizard`, `SettingsDialog` — additional `Toplevel` dialogs (document conversion, language learning, app settings).
- Dubbing Studio engine code lives in the `dubbing/` package (`pipeline`, `stages`, `subtitles`, `video`, `spellcheck`, `config`); its wizard UI is `dubbing/ui_wizard.py`.

**Text chunking:**

Long text is split into ≤280-character chunks before synthesis. `chunk_text_with_offsets()` returns `TextChunk` objects with character offsets used to drive read-aloud line highlighting.

**Settings:**

`settings.json` at the project root persists the default Piper voice label across sessions. Read via `load_app_settings()`, written via `save_app_settings()`.

**Voice files:**

Piper voices (`.onnx` + `.onnx.json`) are stored under `voices/piper/`. The three bundled voices are `hu_HU-anna-medium`, `en_US-lessac-medium`, and `en_GB-alan-medium`. Additional voices downloaded via the wizard are auto-discovered at startup via `discover_local_piper_voices()`.

## Key conventions

- Use `rg` for search; `.rgignore` excludes `.venv`, `output`, `__pycache__`, and `voices/`. Never infer project structure from `.venv`.
- **Language-first UI:** the user picks a Language, then the Engine dropdown is filtered to engines that can speak it (see `engines_supporting_language()`), and the voice control adapts. This is the entry point — don't reintroduce an engine-first flow.
- **Capability registry** (module-level, single source of truth): `LANGUAGE_NAMES`, `XTTS_LANGUAGES`, `POCKET_LANGUAGES`, `POCKET_PREDEFINED_VOICES`, `ENGINE_SUMMARIES`. Piper's language coverage is **derived at runtime** from installed voices via `piper_languages()` / `piper_language_of_code()` — never hardcode a Piper language list.
- Engine resolution is unified in `select_engine(engine, language, has_wav, piper_options)`; `Auto` is language-aware (won't pick Piper for a language with no installed voice). `SynthesisCoordinator.resolve_engine`, `App.resolved_engine`, and the wizard all route through it.
- The `Language` field drives XTTS/Pocket synthesis and filters the Piper voice list; Piper voice **code** remains the source of truth for Piper synthesis.
- Pocket TTS voices come from the `POCKET_PREDEFINED_VOICES` dropdown (not free text); `PocketTTSService` validates the voice name and raises friendly `RuntimeError`s.
- Pass Piper voice identity by **code** (e.g. `hu_HU-anna-medium`), not display label. Labels are UI only.
- The main-window and doc-wizard voice/engine sync methods guard against trace re-entrancy with a `_syncing_*` flag; new widgets accessed there are `hasattr`/`getattr`-guarded so headless unit tests (which mock only some widgets) don't break.
- All GUI updates from background threads must go through `root.after(0, ...)`.
- New machine-level dependencies go in `README.md`; recurring pitfalls go in `KNOWN_ISSUES.md`.

<!-- BEGIN kaizen (managed — do not edit inside this block) -->
This project uses the kaizen harness. The canonical operating contract is **AGENTS.md** — read it first and follow its invariants (worktree-first on the default branch, never `--no-verify`, plan-before-code with grounded evidence, verify contract in `.harness/config.json`).
<!-- END kaizen -->
