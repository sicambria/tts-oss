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

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "Python 3.11 was not found on PATH. Install Python 3.11 and rerun this script." >&2
  exit 1
fi

cd "$ROOT"

if [ ! -d ".venv" ]; then
  "$PYTHON" -m venv .venv
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
PIPER_VOICE_DIR="$ROOT/voices/piper"

"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url "$TORCH_INDEX_URL"
"$VENV_PYTHON" -m pip install -r requirements.txt
mkdir -p "$PIPER_VOICE_DIR"
"$VENV_PYTHON" -m piper.download_voices hu_HU-anna-medium en_US-lessac-medium en_GB-alan-medium --download-dir "$PIPER_VOICE_DIR"

echo
echo "Setup complete."
echo "Installed Piper voices: hu_HU-anna-medium, en_US-lessac-medium, en_GB-alan-medium"
echo "Run the app with: ./run.sh"
