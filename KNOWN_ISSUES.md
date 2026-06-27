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

- Confirm GUI type from code before assuming a web address. In this repo, `Tk()` in `app.py` is definitive.
- Prefer reading the launcher script before answering how to run the app. `run.ps1` and `run.sh` show the real entrypoint.
- Search the repo source, not the virtual environment. Installed package results are usually irrelevant here.
- Document environment assumptions explicitly in setup scripts and README files. Hidden machine-specific assumptions cost time later.
- Prefer an `Auto` backend mode when one engine is clearly better for a specific language or workflow. It keeps the default behavior simple while preserving manual override.
- When a GUI supports multiple engines, keep engine-specific controls visible but make the active/inactive behavior explicit in the UI instead of silently reusing one control for multiple meanings.
- When supporting downloadable model catalogs, pass the stable model code through runtime requests instead of depending on display labels. Labels are UX; codes are the real identity.
