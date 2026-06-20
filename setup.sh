#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TORCH_CHANNEL="${1:-cpu}"

case "$TORCH_CHANNEL" in
  cpu)
    TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
    ;;
  cu121)
    TORCH_INDEX_URL="https://download.pytorch.org/whl/cu121"
    ;;
  *)
    echo "Unsupported torch channel: $TORCH_CHANNEL" >&2
    echo "Usage: ./setup.sh [cpu|cu121]" >&2
    exit 1
    ;;
esac

cd "$ROOT"

VENV_PYTHON="$ROOT/.venv/bin/python"
PIPER_VOICE_DIR="$ROOT/voices/piper"

# Coqui TTS 0.22.0 and torch 2.5.1 only ship wheels for Python >=3.9,<3.12.
# Prefer uv, which can provision a matching interpreter even when the system
# Python is newer (e.g. 3.12+); otherwise fall back to a compatible system Python.
if command -v uv >/dev/null 2>&1; then
  if [ ! -x "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] < (3, 12) else 1)'; then
    rm -rf "$ROOT/.venv"
    uv venv --python 3.11 "$ROOT/.venv"
  fi
  PIP_INSTALL=(uv pip install --python "$VENV_PYTHON")
else
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON="python3.11"
  elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] < (3, 12) else 1)'; then
    PYTHON="python3"
  else
    echo "A compatible Python (>=3.9,<3.12) was not found." >&2
    echo "Install Python 3.11 (or 'uv') and rerun this script." >&2
    exit 1
  fi
  if [ ! -x "$VENV_PYTHON" ]; then
    "$PYTHON" -m venv "$ROOT/.venv"
  fi
  "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
  PIP_INSTALL=("$VENV_PYTHON" -m pip install)
fi

"${PIP_INSTALL[@]}" torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url "$TORCH_INDEX_URL"
"${PIP_INSTALL[@]}" -r requirements.txt
mkdir -p "$PIPER_VOICE_DIR"
"$VENV_PYTHON" -m piper.download_voices hu_HU-anna-medium en_US-lessac-medium en_GB-alan-medium --download-dir "$PIPER_VOICE_DIR"

echo
echo "Setup complete."
echo "Installed Piper voices: hu_HU-anna-medium, en_US-lessac-medium, en_GB-alan-medium"
echo "Run the app with: ./run.sh"
