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
# The Tk GUI additionally needs an interpreter whose Tk was built with Xft, or
# icons and accented characters render as empty boxes. uv's *standalone*
# interpreters bundle a Tk WITHOUT Xft, so we prefer a system/pyenv Python 3.11
# (which links the distro's Xft-enabled Tk) and only fall back to uv's
# interpreter with a warning. uv as a package *installer* is fine either way.
is_compatible_py() {  # $1: python binary; true for 3.9-3.11
  "$1" -c 'import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 12) else 1)' 2>/dev/null
}

BASE_PYTHON=""
# 1. explicit override
if [ -n "${TTS_PYTHON:-}" ] && [ -x "${TTS_PYTHON}" ] && is_compatible_py "${TTS_PYTHON}"; then
  BASE_PYTHON="${TTS_PYTHON}"
fi
# 2. pyenv-built 3.11 (newest first) — these link the system's Xft Tk
if [ -z "$BASE_PYTHON" ]; then
  for cand in $(ls -d "${PYENV_ROOT:-$HOME/.pyenv}"/versions/3.11.*/bin/python3.11 2>/dev/null | sort -rV); do
    if is_compatible_py "$cand"; then BASE_PYTHON="$cand"; break; fi
  done
fi
# 3. distro python3.11 on PATH
if [ -z "$BASE_PYTHON" ] && command -v python3.11 >/dev/null 2>&1 && is_compatible_py "$(command -v python3.11)"; then
  BASE_PYTHON="$(command -v python3.11)"
fi

if [ -n "$BASE_PYTHON" ]; then
  echo "Using interpreter: $BASE_PYTHON"
  desired_prefix="$("$BASE_PYTHON" -c 'import sys; print(sys.base_prefix)')"
  current_prefix=""
  [ -x "$VENV_PYTHON" ] && current_prefix="$("$VENV_PYTHON" -c 'import sys; print(sys.base_prefix)' 2>/dev/null || true)"
  if [ "$current_prefix" != "$desired_prefix" ]; then
    rm -rf "$ROOT/.venv"
    "$BASE_PYTHON" -m venv "$ROOT/.venv"
  fi
  if command -v uv >/dev/null 2>&1; then
    PIP_INSTALL=(uv pip install --python "$VENV_PYTHON")
  else
    "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
    PIP_INSTALL=("$VENV_PYTHON" -m pip install)
  fi
elif command -v uv >/dev/null 2>&1; then
  echo "WARNING: No Xft-capable Python 3.11 found; using uv's standalone interpreter."
  echo "         Its bundled Tk has no Xft, so GUI icons and accented characters"
  echo "         will render as boxes. To fix, install a Tk-enabled Python 3.11"
  echo "         (e.g. 'pyenv install 3.11' with tk-dev present) and re-run setup,"
  echo "         or set TTS_PYTHON=/path/to/python3.11 first. See KNOWN_ISSUES.md."
  if [ ! -x "$VENV_PYTHON" ] || ! is_compatible_py "$VENV_PYTHON"; then
    rm -rf "$ROOT/.venv"
    uv venv --python 3.11 "$ROOT/.venv"
  fi
  PIP_INSTALL=(uv pip install --python "$VENV_PYTHON")
else
  echo "A compatible Python (>=3.9,<3.12) was not found." >&2
  echo "Install Python 3.11 (with tk support) or 'uv', then rerun this script." >&2
  exit 1
fi

"${PIP_INSTALL[@]}" torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url "$TORCH_INDEX_URL"
"${PIP_INSTALL[@]}" -r requirements.txt
mkdir -p "$PIPER_VOICE_DIR"
"$VENV_PYTHON" -m piper.download_voices hu_HU-anna-medium en_US-lessac-medium en_GB-alan-medium --download-dir "$PIPER_VOICE_DIR"

echo
echo "Setup complete."
echo "Installed Piper voices: hu_HU-anna-medium, en_US-lessac-medium, en_GB-alan-medium"
echo "Run the app with: ./run.sh"

# Warn if this interpreter's Tk cannot enumerate system fonts (no Xft). A real
# Xft Tk reports hundreds of families; a coreX-only Tk reports ~58.
if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
  font_count="$("$VENV_PYTHON" - <<'PYEOF' 2>/dev/null || true
import tkinter, tkinter.font as f
r = tkinter.Tk(); r.withdraw()
print(len(f.families()))
PYEOF
)"
  if [ -n "$font_count" ] && [ "$font_count" -le 80 ] 2>/dev/null; then
    echo
    echo "NOTE: This interpreter's Tk reports only $font_count fonts (no Xft); GUI text"
    echo "      and icons will render as boxes. See KNOWN_ISSUES.md for the fix."
  fi
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  DESKTOP_DIR="$HOME/.local/share/applications"
  mkdir -p "$DESKTOP_DIR"
  cat > "$DESKTOP_DIR/local-tts-generator.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Local TTS Generator
Comment=Generate MP3/OGG/WAV from text using local Piper and XTTS voices
Exec=$ROOT/run.sh
Icon=audio-x-generic
Terminal=false
Categories=AudioVideo;Audio;
EOF
  echo "Desktop entry created: $DESKTOP_DIR/local-tts-generator.desktop"
fi
