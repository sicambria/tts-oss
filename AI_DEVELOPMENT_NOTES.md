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

## Lightweight systemic rules introduced

- `KNOWN_ISSUES.md` is the single place for recurring repo pitfalls.
- `AI_DEVELOPMENT_NOTES.md` is the handoff note for future AI contributors.
- `.rgignore` reduces search noise and prevents accidental exploration of the virtual environment.
