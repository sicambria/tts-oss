# Known Issues

This file records issues and learnings discovered during development so they do not need to be rediscovered.

## Confirmed behavior

- The GUI is a native Windows desktop app built with `tkinter`.
- There is no HTTP server, `localhost` endpoint, or browser-based UI in this repo.
- `.\run.ps1` launches the GUI window directly by running `app.py`.
- `Auto` prefers Piper for standard local synthesis.
- If a `Reference WAV` is provided, `Auto` resolves to XTTS because Piper does not do voice cloning in this app.
- The integrated Piper voices are `hu_HU-anna-medium`, `en_US-lessac-medium`, and `en_GB-alan-medium`.

## Known issues

- `setup.ps1` hardcodes Python to `C:\Python311\python.exe`.
- Impact: setup fails on machines where Python 3.11 is installed in a different location.
- Workaround: edit `setup.ps1` or install Python 3.11 at that path.

- First-run XTTS startup is slow.
- Impact: the application may appear idle while model files are downloaded and the model is loaded.
- Workaround: wait for the status log to advance; this is expected on first use.

- XTTS requires license confirmation before first model download.
- Impact: synthesis cannot proceed until the user confirms the license dialog.
- Workaround: accept the dialog only if the intended use complies with Coqui's terms.

- Piper voice choice is independent from the XTTS `Language` field in the GUI.
- Impact: future changes must avoid assuming those two controls always stay in sync.
- Workaround: when changing engine logic, treat Piper voice selection as the source of truth for Piper synthesis and the `Language` field as the XTTS input.

- Naive recursive search can become noisy or slow if it includes `.venv`.
- Impact: code exploration can return thousands of irrelevant results from installed packages.
- Workaround: use `rg` with the repo-level `.rgignore`.

- The workspace may not be a Git checkout.
- Impact: commands such as `git status` can fail even when the project files are otherwise usable.
- Workaround: do not assume Git metadata is present; verify before using Git-based workflows.

## Learnings

- Confirm GUI type from code before assuming a web address. In this repo, `Tk()` in `app.py` is definitive.
- Prefer reading the launcher script before answering how to run the app. `run.ps1` shows the real entrypoint.
- Search the repo source, not the virtual environment. Installed package results are usually irrelevant here.
- Document environment assumptions explicitly in setup scripts and README files. Hidden machine-specific assumptions cost time later.
- Prefer an `Auto` backend mode when one engine is clearly better for a specific language or workflow. It keeps the default behavior simple while preserving manual override.
- When a GUI supports multiple engines, keep engine-specific controls visible but make the active/inactive behavior explicit in the UI instead of silently reusing one control for multiple meanings.
