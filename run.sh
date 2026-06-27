#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "Virtual environment is missing. Run ./setup.sh first." >&2
  exit 1
fi

cd "$ROOT"
"$PYTHON" app.py
