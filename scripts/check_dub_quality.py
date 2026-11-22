"""Thin CLI over dubbing.quality.check (logic stays importable + tested)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from dubbing.quality import main
    raise SystemExit(main())
