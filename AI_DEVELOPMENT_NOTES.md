# AI Development Notes

This file is for future AI-assisted development in this repo.

## Fast repo orientation

1. Read `README.md`.
2. Read `run.ps1` and `setup.ps1`.
3. Read `app.py`.
4. Check `KNOWN_ISSUES.md` before changing setup or runtime behavior.

## Repo-specific assumptions

- This is a Windows-only desktop application.
- The GUI is `tkinter`, not a web framework.
- The main app entrypoint is `app.py`.
- The standard launcher is `.\run.ps1`.
- The integrated Piper voices are `hu_HU-anna-medium`, `en_US-lessac-medium`, and `en_GB-alan-medium`.
- `Auto` prefers Piper unless the request uses XTTS-only functionality such as reference voice cloning.
- Additional Piper voices can be added from the in-app wizard and are discovered from `voices\piper` at startup.

## Search discipline

- Use `rg` from the repo root.
- Let `.rgignore` exclude `.venv`, `output`, and `__pycache__`.
- Do not infer project structure from files inside `.venv`.

## Before answering operational questions

- Verify whether the question is about setup, launch, or runtime behavior.
- Check the launcher scripts before describing how the app is started.
- Check whether the answer depends on local-machine assumptions such as Python path, GPU availability, or downloaded XTTS assets.

## When updating setup or docs

- Keep Python version and installation-path assumptions explicit.
- If you add a new machine dependency, document it in `README.md`.
- If you discover a recurring pitfall, add it to `KNOWN_ISSUES.md`.
- If you integrate a new voice model, keep the local cache path and download mechanism explicit.
- If you add engine-specific GUI controls, ensure their enabled or ignored state is visible to the user.
- If you add downloadable voices, keep the runtime request keyed by voice code, not by display label.

## Lightweight systemic rules introduced

- `KNOWN_ISSUES.md` is the single place for recurring repo pitfalls.
- `AI_DEVELOPMENT_NOTES.md` is the handoff note for future AI contributors.
- `.rgignore` reduces search noise and prevents accidental exploration of the virtual environment.
- `Auto` engine selection encodes the preferred backend per language instead of relying on tribal knowledge.
