# Coqui XTTS MP3 GUI

Small Windows desktop app for generating MP3 files from long Hungarian and English texts with Coqui XTTS v2.

This is a local desktop GUI built with `tkinter`. It does not expose a browser UI or `localhost` web server.

## What it does

- Uses `tts_models/multilingual/multi-dataset/xtts_v2`
- Supports `hu` and `en`
- Accepts long text and splits it into smaller chunks before synthesis
- Exports a single MP3 file
- Lets you use either:
  - a built-in XTTS speaker name such as `Ana Florence`
  - a reference voice file for cloning

## Requirements

- Windows
- Python 3.11
- Enough disk space for the XTTS model download
- CPU works, but GPU is much faster if you have a compatible PyTorch install

Coqui TTS currently documents Python `>=3.9, <3.12` for installation:

- GitHub README: https://github.com/coqui-ai/TTS
- XTTS docs: https://docs.coqui.ai/en/latest/models/xtts.html

## Setup

CPU setup:

```powershell
.\setup.ps1
```

CUDA 12.1 setup:

```powershell
.\setup.ps1 -TorchChannel cu121
```

## Run

```powershell
.\run.ps1
```

This opens a native Windows window on the same machine.

## Usage notes

- Leave `Reference WAV` empty to use the built-in speaker name.
- If you provide a reference voice file, the app uses that instead of the built-in speaker.
- The first synthesis run is slow because XTTS downloads and loads the model.
- The first XTTS download requires license confirmation for Coqui's CPML or a commercial license.
- Long text is chunked conservatively to reduce failures on very large inputs.
- Output is written as `192k` MP3.

## Troubleshooting

- If you are looking for a web address, there is none. The GUI is a desktop window, not a browser app.
- `setup.ps1` currently expects Python 3.11 at `C:\Python311\python.exe`. If your Python installation lives elsewhere, update the script or install Python there.
- The first successful synthesis can take a long time because XTTS downloads model files and initializes the runtime.
- The first XTTS download requires license confirmation. The app prompts for this when synthesis starts.
- Repo-wide text search should exclude `.venv`, `output`, and `__pycache__`. A repo-level `.rgignore` file is included for that purpose.

## Development Notes

- Known issues and operational learnings are tracked in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
- Repo-specific guidance for future AI or automation work is tracked in [AI_DEVELOPMENT_NOTES.md](AI_DEVELOPMENT_NOTES.md).

## Recommended voice workflow

- For English and Hungarian with one consistent voice, use a clean 6-15 second reference sample.
- Use mono or regular speech audio without background music.
- Keep the same reference file for both languages if you want one cloned voice across both.
