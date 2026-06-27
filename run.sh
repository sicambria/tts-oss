#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "Virtual environment is missing. Run ./setup.sh first." >&2
  exit 1
fi

cd "$ROOT"
# On Wayland, set XMODIFIERS so the XIM bridge is available to this X11 app.
export XMODIFIERS="${XMODIFIERS:-@im=ibus}"
"$PYTHON" app.py
