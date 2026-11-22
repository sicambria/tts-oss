"""CLI: dub a media file to Hungarian (or other target) using local Piper/XTTS.

Example:
  .venv/bin/python scripts/dub_video.py "/home/user/Video.mp4" --target hu --engine Piper --out output/
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dub audio/video locally.")
    ap.add_argument("input", help="audio/video file")
    ap.add_argument("--target", default="hu")
    ap.add_argument("--source-lang", default="en")
    ap.add_argument("--engine", default="Piper")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--separation", action="store_true")
    ap.add_argument("--keep-bg", type=float, default=0.2)
    ap.add_argument("--burn-in", action="store_true")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)

    from dubbing.config import DubJob
    from dubbing.pipeline import DubPipeline

    job = DubJob(input=Path(args.input), source_lang=args.source_lang,
                 target_lang=args.target, engine=args.engine,
                 burn_in=args.burn_in, output_dir=Path(args.out),
                 allow_video=True, separation_enabled=args.separation,
                 whisper_model=args.whisper_model, keep_bg_ratio=args.keep_bg)
    job.validate()

    from app import PiperService
    from app import SynthesisRequest

    piper = PiperService(print)
    voice = "hu_HU-anna-medium" if args.target == "hu" else "en_US-lessac-medium"

    def synth(text: str, hint: Path) -> Path:
        out = hint.parent / f"{hint.stem}_tts.wav"
        req = SynthesisRequest(text=text, language=args.target, output_file=out,
                               engine="Piper", piper_voice_label=voice,
                               piper_voice_code=voice, speaker_name="",
                               speaker_wav="", speed=1.0)
        return Path(piper.synthesize(req))

    with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
        work = Path(tmp)
        pipe = DubPipeline(job, log=print)
        out = pipe.run(work, synthesize=synth, full=True)
        # Persist work artifacts (srt + timeline) next to the output for quality checks.
        import shutil
        import time
        keep = Path(args.out) / f"dub_work_{int(time.time())}"
        keep.mkdir(parents=True, exist_ok=True)
        for name in ("dub.srt", "dub_timeline.wav", "dub_mixed.wav", "extracted.wav"):
            src = work / name
            if src.is_file():
                try:
                    shutil.copy(src, keep / name)
                except Exception:
                    pass
    print(f"DONE: {out}")
    print(f"WORK: {keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
