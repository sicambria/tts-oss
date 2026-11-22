#!/usr/bin/env bash
# Isolated audio-separator env (numpy>=2) — the repo venv stays pinned at
# numpy==1.26.4 for Piper/gruut, which audio-separator 0.48 rejects.
# Usage: scripts/setup_separator_env.sh
set -euo pipefail
VENV_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tts-oss-sep/.venv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3.11 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q "audio-separator==0.48.0"
"$VENV_DIR/bin/python" -c "import audio_separator, numpy; print('separator env ok, numpy', numpy.__version__)"
echo "AUDIO-SEPARATOR READY: $VENV_DIR/bin/audio-separator"
