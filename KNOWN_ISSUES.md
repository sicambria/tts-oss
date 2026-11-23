# Known Issues

This file records issues and learnings discovered during development so they do not need to be rediscovered.

## Confirmed behavior

- The GUI is a native desktop app built with `tkinter`.
- There is no HTTP server, `localhost` endpoint, or browser-based UI in this repo.
- `run.ps1` on Windows and `run.sh` on Linux/macOS launch the GUI directly by running `app.py`.
- `Auto` prefers Piper for standard local synthesis.
- If a `Reference WAV` is provided, `Auto` resolves to XTTS because Piper does not do voice cloning in this app.
- The integrated Piper voices are `hu_HU-anna-medium`, `en_US-lessac-medium`, and `en_GB-alan-medium`.
- Additional Piper voices can be downloaded from the in-app wizard and stored under `voices/piper`.

## Known issues

- Linux support depends on system packages outside Python.
- Impact: setup may succeed but the GUI or audio playback can still fail if `tkinter` or SDL-related audio libraries are missing.
- Workaround: install platform packages such as `python3-tk` and the audio stack required by `pygame`.

- Pocket TTS 2.1.0 declares a `numpy>=2` dependency, but the Piper dependency `gruut` requires `numpy<2.0.0`. In practice both work with numpy 1.26.4, so the pinned `numpy==1.26.4` in `requirements.txt` avoids the conflict.
- Impact: pip may print a "possibly conflicting dependencies" warning during install, but the application runs correctly.
- Workaround: ignore the warning; if a future version of pocket-tts actually requires numpy 2.x at runtime, upgrade numpy or adjust `requirements.txt`.

- First-run XTTS startup is slow.
- Impact: the application may appear idle while model files are downloaded and the model is loaded.
- Workaround: wait for the status log to advance; this is expected on first use.

- XTTS requires license confirmation before first model download.
- Impact: synthesis cannot proceed until the user confirms the license dialog.
- Workaround: accept the dialog only if the intended use complies with Coqui's terms.

- Piper voice choice is independent from the XTTS `Language` field in the GUI.
- Impact: future changes must avoid assuming those two controls always stay in sync.
- Workaround: when changing engine logic, treat Piper voice selection as the source of truth for Piper synthesis and the `Language` field as the XTTS input.

- uv's standalone Python ships a Tk without Xft, so the GUI renders icons and accented characters as empty boxes.
- Impact: with a uv-provisioned interpreter (`uv venv --python 3.11`), `tkinter` only sees the ~58 X11 core *bitmap* fonts — every font name (e.g. `DejaVu Sans`) silently falls back to `fixed`, which has no emoji/symbol glyphs and no Latin Extended-A (so `ő`, `ű` show as boxes). This is a property of the interpreter's bundled Tk (both Tk 8.6 and 9.0 standalone builds), not of `app.py`; changing font names cannot fix it. A working Tk reports hundreds of font families; check with `python -c "import tkinter,tkinter.font as f; r=tkinter.Tk(); print(len(f.families()))"`.
- Workaround: use a Python 3.11 whose Tk links the distro's Xft-enabled Tk. Easiest is `pyenv install 3.11` with `tk-dev`/`tcl-dev` installed first; `setup.sh` now auto-prefers a pyenv/system 3.11 over uv's interpreter (uv is still used as the fast package *installer*). Override explicitly with `TTS_PYTHON=/path/to/python3.11 ./setup.sh`. Verify after setup: family count should be in the hundreds, not ~58.

- Naive recursive search can become noisy or slow if it includes `.venv`.
- Impact: code exploration can return thousands of irrelevant results from installed packages.
- Workaround: use `rg` with the repo-level `.rgignore`.

- The workspace may not be a Git checkout.
- Impact: commands such as `git status` can fail even when the project files are otherwise usable.
- Workaround: do not assume Git metadata is present; verify before using Git-based workflows.

## Learnings

- Dubbing music+speech: never default Whisper VAD on for songs. Silero VAD drops sung vocals along with the music (real case: 5/52 segments kept, whole sung body lost) and `no_speech_prob` cannot post-filter (real sung segs scored 0.75–0.94). Use VAD-off + `condition_on_previous_text=False` + `hallucination_silence_threshold≈2s`; vocal separation (opt-in) is the proper music-content path.
- NLLB needs FLORES codes on both sides. Passing short codes (`hu`) to `forced_bos_token_id` silently yields a wrong token (300 vs 256071 for `hun_Latn`) and gibberish output — map via a `nllb_code()` helper and set `tok.src_lang` too.
- Song-dub timing: never time-stretch TTS to fill melodic slots (measured: 33/49 slowed, worst 5x). Place at natural speed from slot start; squeeze at most 1.5x, then spill. Fuse sub-1.5 s micro-slots pre-translate (capped span) — better fit and better MT context.
- NLLB loops on long merged inputs: `no_repeat_ngram_size=3` + `repetition_penalty=1.2` (verified: runaway tail gone, style intact). Greedy Whisper loops need the same treatment on the STT side (`defuse_repetition`, keep refrains).
- Deterministic STT needs open confidence floors: temperature=0.0 alone dropped 10 quiet tail verses; log_prob -2.0 + no_speech 1.0 recovered them with gaps staying clean.
- Transcribe the MIX for songs, not the vocal stem: separator artifacts hallucinate confidently ("coffee/sunflower" at stem RMS 0.033, same band as real singing) while VAD-on-stem drops quiet real verses. The stem feeds only the bg mix + clone reference.
- audio-separator filename trap: stems are `name_(Vocals)_Model.wav` and the MODEL name contains "vocal" (Kim_Vocal_2) — match the parenthesized label, never a bare substring, or every stem matches.
- audio-separator 0.48 cannot live in this repo's venv (needs numpy>=2 + beartype<0.19; repo pins numpy 1.26.4 for gruut/Piper and pocket-tts needs beartype>=0.22.5). Run it from an isolated `~/.cache/tts-oss-sep` venv via subprocess (`scripts/setup_separator_env.sh`); in-process import stays as the fast path for numpy>=2 envs.
- Wire new pipeline inputs end to end. The Dubbing Studio `separation` checkbox was saved to settings but never reached `DubJob` (no field), and `mix_with_bg` was always called with `bg=None`, so background music was silently dropped. A checkbox that reaches no job field is a dead control — test the wiring, not just the widget.

- Confirm GUI type from code before assuming a web address. In this repo, `Tk()` in `app.py` is definitive.
- Prefer reading the launcher script before answering how to run the app. `run.ps1` and `run.sh` show the real entrypoint.
- Search the repo source, not the virtual environment. Installed package results are usually irrelevant here.
- Document environment assumptions explicitly in setup scripts and README files. Hidden machine-specific assumptions cost time later.
- Prefer an `Auto` backend mode when one engine is clearly better for a specific language or workflow. It keeps the default behavior simple while preserving manual override.
- When a GUI supports multiple engines, keep engine-specific controls visible but make the active/inactive behavior explicit in the UI instead of silently reusing one control for multiple meanings.
- When supporting downloadable model catalogs, pass the stable model code through runtime requests instead of depending on display labels. Labels are UX; codes are the real identity.
- A "can't type character X" symptom in a Tk GUI is often a missing-glyph *rendering* problem, not a keyboard/input-method problem. The character is typed correctly but the font lacks the glyph, so it shows as a box. Verify font glyph coverage before chasing IME/layout: `python -c "import tkinter,tkinter.font as f; r=tkinter.Tk(); print(len(f.families()))"` — a healthy Xft Tk reports hundreds of families; a coreX-only Tk reports ~58 and falls back to the `fixed` bitmap font.
- Diagnose GUI rendering with a font probe, not a launch. "Process started, exit 0" cannot confirm a rendering fix; resolving `DejaVu Sans` to itself and a high family count is the screenshot-free proxy that actually proves it.
- Distinguish uv-the-installer from uv-the-interpreter-provisioner. `uv pip install --python <venv>` is fine for any interpreter, but `uv venv --python 3.11` provisions a standalone Python whose bundled Tk lacks Xft. For Tk GUI apps on Linux, build the venv from a system/pyenv Python and use uv only to install packages.
- Don't split one symptom into several root causes prematurely. The boxed icons, boxed accented characters, and "can't type accents" were all the same Tk/Xft issue; treating them as separate (font + input-method) produced a fix and docs for a problem that did not exist.
- GUI defaults are the product for most users: the Dubbing Studio once defaulted to no-separation (music lost), video-refused (dev gate leaked into UI), and TTS-panel engine (wrong voice) — and every bad default shipped a bad dub silently. Best defaults + auto-install + deliverable audit now guard this; `dub_defaults()` keeps them testable without Tk.
- Never offer a repo-venv pip install for a package that conflicts with the repo's pins. audio-separator needs numpy>=2 while this repo pins numpy 1.26.4 — one click broke Piper. Conflicting tools live in isolated envs with subprocess bridges; `pip_missing_specs` must never list them (regression-tested).
