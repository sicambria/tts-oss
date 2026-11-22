"""Repo-owned 30s EN fixture: Piper synth, 3 segments, expected norm hash."""
from __future__ import annotations

import sys
from pathlib import Path

SEGMENTS = [
    (0.0, 9.5, "Hello, welcome to this local dubbing test."),
    (10.0, 19.5, "This is the second sentence for timing checks."),
    (20.0, 29.5, "And this is the final line of the fixture."),
]


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dubbing.config import Segment
    from dubbing.subtitles import srt_norm_hash
    from dubbing.subtitles import write_srt
    out = Path(__file__).resolve().parents[1] / "input" / "dub_fixture"
    out.mkdir(parents=True, exist_ok=True)
    segs = [Segment(s, e, text=t, translated=t) for s, e, t in SEGMENTS]
    srt = write_srt(segs, out / "fixture_en.srt", translated=True)
    print(f"Wrote {srt}")
    print(f"NORM_HASH={srt_norm_hash(segs)}")
    print("WAV: synthesize each segment with Piper en_US-lessac-medium and concat to 30s for manual tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
