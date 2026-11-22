"""CLI: dub a media file (song-aware: no slow-downs, spill-over, merge micros).

Example (music video, cloned voice, burned subs):
  .venv/bin/python scripts/dub_video.py "~/Video.mp4" --target hu --engine XTTS \\
      --separation --speaker-auto --burn-in --out output/

Needs: faster-whisper + NLLB cached; --separation needs the isolated env
from scripts/setup_separator_env.sh; --engine XTTS needs Coqui TTS installed.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _clip_wav(src: Path, start: float, length: float, out: Path) -> Path:
    import subprocess

    from dubbing import ffmpeg_path
    subprocess.run([ffmpeg_path(), "-hide_banner", "-y", "-i", str(src),
                    "-ss", f"{start:.1f}", "-t", f"{length:.1f}", str(out)],
                   check=True, capture_output=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dub audio/video locally (song-aware).")
    ap.add_argument("input", help="audio/video file")
    ap.add_argument("--target", default="hu")
    ap.add_argument("--source-lang", default="en")
    ap.add_argument("--engine", default="XTTS", choices=["Piper", "XTTS"])
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--separation", action="store_true",
                    help="split vocals/music (isolated env); keeps music, STT on clean vocals")
    ap.add_argument("--keep-bg", type=float, default=0.2)
    ap.add_argument("--speaker-wav", default="",
                    help="XTTS reference voice; with --speaker-auto derive from the input")
    ap.add_argument("--speaker-auto", action="store_true",
                    help="derive XTTS reference from separated vocals (or intro speech)")
    ap.add_argument("--burn-in", dest="burn_in", action="store_true", default=True)
    ap.add_argument("--no-burn-in", dest="burn_in", action="store_false")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)

    from dubbing import is_video_input
    from dubbing.config import DubJob
    from dubbing.pipeline import DubPipeline

    burn_in = bool(args.burn_in) and is_video_input(args.input)
    job = DubJob(input=Path(args.input), source_lang=args.source_lang,
                 target_lang=args.target, engine=args.engine,
                 burn_in=burn_in, output_dir=Path(args.out),
                 allow_video=True, separation_enabled=args.separation,
                 whisper_model=args.whisper_model, keep_bg_ratio=args.keep_bg)
    job.validate()

    from app import SynthesisRequest

    if args.engine == "XTTS":
        from app import XTTSService
        xtts = XTTSService(print)
        ref = args.speaker_wav.strip()
        auto_ref: Path | None = None

        def synth(text: str, hint: Path) -> Path:
            out = hint.parent / f"{hint.stem}_tts.wav"
            req = SynthesisRequest(text=text, language=args.target, output_file=out,
                                   engine="XTTS v2", piper_voice_label="",
                                   piper_voice_code="", speaker_name="Ana Florence",
                                   speaker_wav=ref, speed=1.0)
            return Path(xtts.synthesize(req))
    else:
        from app import PiperService
        piper = PiperService(print)
        voice = "hu_HU-anna-medium" if args.target == "hu" else "en_US-lessac-medium"

        def synth(text: str, hint: Path) -> Path:  # type: ignore[misc]
            out = hint.parent / f"{hint.stem}_tts.wav"
            req = SynthesisRequest(text=text, language=args.target, output_file=out,
                                   engine="Piper", piper_voice_label=voice,
                                   piper_voice_code=voice, speaker_name="",
                                   speaker_wav="", speed=1.0)
            return Path(piper.synthesize(req))

    with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
        work = Path(tmp)
        if args.engine == "XTTS" and args.speaker_auto and not ref:
            # Derive the clone reference: prefer separated vocals (clean),
            # else the spoken intro of the mix (music underneath, worse).
            from dubbing import stages
            wav = stages.extract_audio(job.input, work / "ref_extracted.wav")
            if args.separation:
                try:
                    vocal, _ = stages.separate_background(wav, work / "ref_sep", True)
                    auto_ref = work / "ref_vocal_cut.wav"
                    _clip_wav(vocal, 0.0, 30.0, auto_ref)
                    ref = str(auto_ref)
                except Exception as exc:
                    print(f"NOTE: vocal-stem reference failed ({exc}); using intro speech.")
            if not ref:
                auto_ref = work / "ref_intro.wav"
                _clip_wav(wav, 1.0, 21.0, auto_ref)
                ref = str(auto_ref)
            print(f"Clone reference: {ref}")
        pipe = DubPipeline(job, log=print)
        out = pipe.run(work, synthesize=synth, full=True)
        import shutil
        import time
        keep = Path(args.out) / f"dub_work_{int(time.time())}"
        keep.mkdir(parents=True, exist_ok=True)
        for name in ("dub.srt", "dub_transcript.json", "dub_timeline.wav", "dub_mixed.wav", "extracted.wav"):
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
