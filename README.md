# Local TTS MP3 GUI

Small Windows desktop app for generating MP3 files from long Hungarian and English texts with local TTS engines.

This is a local desktop GUI built with `tkinter`. It does not expose a browser UI or `localhost` web server.

## What it does

- Uses Piper for fast Hungarian output with `hu_HU-anna-medium`
- Uses Piper for U.S. English with `en_US-lessac-medium`
- Uses Piper for British English with `en_GB-alan-medium`
- Uses `tts_models/multilingual/multi-dataset/xtts_v2` for XTTS
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

This installs Python dependencies and downloads the Piper voice files for:

- `hu_HU-anna-medium`
- `en_US-lessac-medium`
- `en_GB-alan-medium`

All Piper voice files are stored in `voices\piper`.

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

- `Engine = Auto` prefers Piper for normal local synthesis and switches to XTTS if you provide a `Reference WAV`.
- The `Piper voice` dropdown lets you choose between Hungarian, U.S. English, and British English Piper voices.
- `Read Aloud` synthesizes the current textbox content to a temporary audio file and plays it locally.
- `Pause`, `Resume`, and `Stop` control local playback for the current read-aloud preview.
- `Voice Wizard` loads the official Piper voice catalog, lets you download additional voice models, and can set a default Piper voice for the app.
- `XTTS v2` is the option that supports built-in speaker selection and reference voice cloning.
- Leave `Reference WAV` empty to use the built-in speaker name.
- If you provide a reference voice file, the app uses that instead of the built-in speaker.
- The first synthesis run is slow because XTTS downloads and loads the model.
- The first XTTS download requires license confirmation for Coqui's CPML or a commercial license.
- Long text is chunked conservatively to reduce failures on very large inputs.
- Output is written as `192k` MP3.

## Troubleshooting

- If you are looking for a web address, there is none. The GUI is a desktop window, not a browser app.
- `setup.ps1` currently expects Python 3.11 at `C:\Python311\python.exe`. If your Python installation lives elsewhere, update the script or install Python there.
- If fast local output is the goal, prefer `Engine = Auto` or `Engine = Piper`.
- If Piper fails to start, rerun `.\setup.ps1` to ensure `piper-tts` and the files under `voices\piper` are present.
- If playback controls do nothing, check that Windows audio output is available and that `pygame` installed successfully during setup.
- The first successful synthesis can take a long time because XTTS downloads model files and initializes the runtime.
- The first XTTS download requires license confirmation. The app prompts for this when synthesis starts.
- Repo-wide text search should exclude `.venv`, `output`, and `__pycache__`. A repo-level `.rgignore` file is included for that purpose.

## Development Notes

- Known issues and operational learnings are tracked in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
- Repo-specific guidance for future AI or automation work is tracked in [AI_DEVELOPMENT_NOTES.md](AI_DEVELOPMENT_NOTES.md).

## Recommended voice workflow

- For the best local speed/quality balance in Hungarian, use Piper with `hu_HU-anna-medium`.
- For U.S. English Piper output, use `en_US-lessac-medium`.
- For British English Piper output, use `en_GB-alan-medium`.
- For English and Hungarian with one consistent voice, use a clean 6-15 second reference sample.
- Use mono or regular speech audio without background music.
- Keep the same reference file for both languages if you want one cloned voice across both.

## Voice Sources

- Piper voice catalog and samples: https://rhasspy.github.io/piper-samples/
- The integrated Piper voices are `hu_HU-anna-medium`, `en_US-lessac-medium`, and `en_GB-alan-medium`.
