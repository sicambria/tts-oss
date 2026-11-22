# AGENTS.md

Canonical instructions for AI coding agents in this repo. Read this first, then the files it points to.

## Orientation (read in this order)

1. `README.md` — what the app is and how users run it.
2. `run.sh` / `run.ps1`, `setup.sh` / `setup.ps1` — the real entrypoints. Read them before answering how to run/install.
3. `app.py` — the entire app (~6900 lines, single file, no module split).
4. `KNOWN_ISSUES.md` — confirmed behavior, environment pitfalls, past misdiagnoses. Check before changing setup/runtime.
5. `ANTIPATTERNS.md` — mandatory code-review checklist. Check during planning and before committing.
6. `AI_DEVELOPMENT_NOTES.md` — handoff notes for AI contributors.

## What this repo is

- Native `tkinter` desktop GUI (`Tk()` in `app.py`). **No browser UI, no localhost server, no HTTP endpoint. Never suggest one.**
- Launch: `./run.sh` (Linux/macOS), `.\run.ps1` (Windows). Setup: `./setup.sh [cpu|cu121]`, `.\setup.ps1 [-TorchChannel cu121]`.
- Engines: `Auto` (default) / `Piper` / `XTTS v2` / `Pocket TTS`. XTTS model: `tts_models/multilingual/multi-dataset/xtts_v2`.
- Everything lives in `app.py`: `SynthesisCoordinator`, `PiperService`, `XTTSService`, `PocketTTSService`, `AudioPlayer` (pygame), `App` (Tk root), `PiperVoiceWizard`, `DocumentToAudioWizard`, `DubbingWizard`, `LanguageLearningWizard`.
- Tests: `tests/` (pytest). Hooks: `.githooks/pre-commit` (ruff + pytest cov≥50), `.githooks/pre-push` (ruff + pytest cov≥85). Coverage exclusions in `pyproject.toml`.

## Commands

```bash
./run.sh                          # run GUI (Linux/macOS)
./setup.sh                        # CPU setup
./setup.sh cu121                  # CUDA 12.1
.venv/bin/python -m pytest        # full suite (must pass before push)
.venv/bin/python -m pytest tests/test_text_chunking.py  # focused example
.venv/bin/ruff check app.py tests/  # lint (must pass)
git diff --check                  # whitespace check
rg <pattern>                      # search (never grep .venv manually)
```

## Architecture rules (do not violate)

- **Language-first UI.** User picks Language → Engine dropdown filters via `engines_supporting_language()` → voice control adapts. Never reintroduce engine-first flow.
- **Capability registry is single source of truth:** `LANGUAGE_NAMES`, `XTTS_LANGUAGES`, `POCKET_LANGUAGES`, `POCKET_PREDEFINED_VOICES`, `ENGINE_SUMMARIES`. Piper coverage is **derived at runtime** via `piper_languages()` / `piper_language_of_code()` — never hardcode a Piper language list.
- **Engine resolution is unified** in `select_engine(engine, language, has_wav, piper_options)`. `Auto` is language-aware (won't pick Piper with no installed voice for that language). `SynthesisCoordinator.resolve_engine`, `App.resolved_engine`, wizard handlers all route through it. When handling engine change in a wizard, resolve `Auto` **before** setting field state (past bug: `61b9db8`).
- **Voice identity by code, not label.** Piper code e.g. `hu_HU-anna-medium`; Pocket voice from `POCKET_PREDEFINED_VOICES` dropdown (validated, friendly `RuntimeError`). Labels are UI-only.
- **Chunking contract** (`chunk_text_with_offsets` → `TextChunk(text, start, end)`): sentence/paragraph-boundary-first, clause fallback, word fallback; chunks are non-overlapping monotonic `source[start:end].strip()` slices; whitespace gaps only. Never replace with word-only splitting for highlighting (caused XTTS duplicate-word RCA, `cf86955`, `plans/2026-08_RCA_xtts-duplicate-audio.md`). Keep XTTS `split_sentences=True`.
- **Threading:** all GUI updates from workers via `root.after(0, ...)`. **Never read Tk vars on a worker thread** — snapshot all UI state (page range, format, engine, voice, quality, speed) on the UI thread and pass an immutable snapshot to the worker (past bug: pages 61–70 synthesized full doc, `plans/2026-08_RCA_page-range-worker-snapshot.md`).
- **Trace guards:** voice/engine sync methods use `_syncing_*` flags; guard new widget access with `hasattr`/`getattr` so headless tests (partial widget mocks) don't break.
- **Empty-text early exit** before loading voice state in synthesis paths (past bug: `61b9db8`).
- **WAV cache:** `_voice_cache_path` returns `None` for WAV file paths — never cache reference-WAV voices as safetensors (past stale-cache bug: `61b9db8`).

## Never repeat these past errors

1. **No web server.** Confirm GUI type from code (`Tk()`), not assumption. Past agents repeatedly suggested `localhost`/browser URLs.
2. **Search discipline.** Use `rg` from root; `.rgignore` excludes `.venv/`, `output/`, `__pycache__/`, `voices/`. Never infer project structure from `.venv`.
3. **Tk/Xft font issue (the big one).** Boxed icons + boxed `ő`/`ű` + "can't type accents" are ONE root cause: uv's standalone Python bundles Tk **without Xft** (~58 core bitmap fonts, everything falls back to `fixed`). Fix is interpreter choice (pyenv/system Python 3.11 with `tk-dev`, `setup.sh` auto-prefers it, `TTS_PYTHON=` override), never font-name changes. Verify with font probe (`len(font.families())` in hundreds), not "process started, exit 0". Do NOT add `XMODIFIERS`/IME fixes — that was a phantom second diagnosis (`5a06722`, `dcacc6e`, `debc61a`, `KNOWN_ISSUES.md`).
4. **Non-ASCII voice URLs.** Percent-encode with `quote()` using the catalog `files` dict; `urlopen` raises `UnicodeEncodeError` on e.g. `pt_PT-tugão-medium` otherwise (`04dd8b1`).
5. **Piper speed API.** Use `SynthesisConfig`, not bare `length_scale` kwarg (`b85dfcd`).
6. **Missing imports break features.** `DoubleVar` was forgotten for the speed slider (`b81f64a`). After adding widgets, run focused tests + full suite.
7. **Hook venv paths.** Hooks must use `$SCRIPT_DIR/.venv/bin/...`, broke once (`315769d`). Pre-push gate is cov≥85 — add tests with features.
8. **numpy pin.** Keep `numpy==1.26.4`: Pocket TTS 2.1.0 wants `numpy>=2`, `gruut` (Piper) wants `numpy<2.0.0`. 1.26.4 satisfies both at runtime; pip warning is expected and ignored.
9. **Linux system deps.** `python3-tk` + SDL audio libs are outside pip. Document new machine deps in `README.md`, pitfalls in `KNOWN_ISSUES.md`.
10. **Don't commit generated noise.** `settings.json` / `settings.json.bak` churn polluted history — they are git-ignored; don't force-add them.

## Before committing

- Always commit when the task is done. Do not leave changes uncommitted in the working tree.
- Run: `ruff check`, full `pytest`, `git diff --check`. Pre-push requires coverage ≥85%.
- Walk the `ANTIPATTERNS.md` checklist: no `sys.path.insert` hacks, numeric `Entry` validation, config-corruption warning+backup, temp-file tracking (no fixed-delay `after` unlink), specific exceptions in workers, cache hot paths, labels match behavior, context menus on all `Entry`/`Text`, normalized (NFD+strip+lower) user-input matching, dependency health check at feature entry.
- Keep Python floor `>=3.9,<3.12` (Coqui wheels). `pyproject.toml`: ruff line-length 120, `E402/E501` ignored.
- Docs: new machine dependency → `README.md`; recurring pitfall → `KNOWN_ISSUES.md`.
