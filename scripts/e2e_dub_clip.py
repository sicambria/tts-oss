"""End-to-end dub smoke: EN Piper clip -> faster-whisper -> NLLB -> HU Piper dub -> mp3 + mp4 burn-in.

Real models, no mocks. Requires cached faster-whisper-small + NLLB-1.3B
(both in ~/.cache/huggingface here) and local Piper voices.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "output" / "e2e_dub"

EN_TEXT = "Hello world. This is a short dubbing test."
EN_VOICE = "en_US-lessac-medium"
HU_VOICE = "hu_HU-anna-medium"


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def main() -> int:
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    from app import PiperService
    from app import SynthesisRequest

    piper = PiperService(log)

    def synth(text: str, voice_code: str, out: Path) -> Path:
        req = SynthesisRequest(
            text=text, language="en", output_file=out, engine="Piper",
            piper_voice_label=voice_code, piper_voice_code=voice_code,
            speaker_name="", speaker_wav="", speed=1.0,
        )
        return piper.synthesize(req)

    # 1. EN source clip (two sentences -> two segments expected)
    log("synthing EN source clip…")
    clip = synth(EN_TEXT, EN_VOICE, WORK / "clip_en.wav")

    # 2. faster-whisper small (cached)
    from dubbing.stages import transcribe
    log("transcribing (faster-whisper-small)…")
    segs = transcribe(clip, "small")
    log(f"segments: {[(round(s.start, 2), round(s.end, 2), s.text) for s in segs]}")
    assert len(segs) >= 1, "expected at least 1 segment"
    assert any("hello" in s.text.lower() or "world" in s.text.lower() for s in segs), f"transcription off: {[s.text for s in segs]}"

    # 3. NLLB EN->HU (cached, CPU)
    from dubbing.stages import translate_segments
    log("translating (NLLB-200-1.3B, CPU)…")
    segs = translate_segments(segs, "eng_Latn", "hun_Latn")
    for s in segs:
        log(f"HU: {s.translated}")
    assert all(s.translated.strip() for s in segs), "empty translation"

    # 4. spellcheck on translation (spylls, must be available)
    from dubbing import spellcheck
    log(f"spell backend={spellcheck.backend()} available={spellcheck.available('hu_HU')}")
    assert spellcheck.available("hu_HU"), "hu_HU spellcheck unavailable"

    # 5. full pipeline: synth HU + fit + timeline + mp3 (+ srt)
    from dubbing.config import DubJob
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=clip, source_lang="en", target_lang="hu", engine="Piper",
                 output_dir=WORK, audio_output_format="mp3")
    made: list[Path] = []

    def hu_synth(text: str, hint: Path) -> Path:
        out = hint.parent / f"hu_{len(made):03d}.wav"
        made.append(out)
        req = SynthesisRequest(
            text=text, language="hu", output_file=out, engine="Piper",
            piper_voice_label=HU_VOICE, piper_voice_code=HU_VOICE,
            speaker_name="", speaker_wav="", speed=1.0,
        )
        return piper.synthesize(req)

    # feed known segments: bypass STT/MT (already proven above), exercise dub path
    from dubbing import stages as stages_mod
    pipe = DubPipeline(job, log=log)
    out = pipe.run(
        WORK / "job", extract=lambda s, d: (d.write_bytes(s.read_bytes()), d)[1],
        transcribe=lambda v: segs, translate=lambda x, s, t: x,
        synthesize=hu_synth, full=True,
    )
    log(f"DUBBED AUDIO: {out} ({out.stat().st_size} bytes)")
    assert out.suffix == ".mp3" and out.stat().st_size > 1000
    srt = WORK / "job" / "dub.srt"
    assert srt.is_file(), "sidecar SRT missing"
    _ = stages_mod  # keep import used

    # 6. video mux + burn-in on a 12s color clip
    import subprocess

    from dubbing import ffmpeg_path
    from dubbing import has_libass
    log(f"libass bundled: {has_libass()}")
    assert has_libass(), "bundled ffmpeg lacks libass"
    mp4 = WORK / "clip_src.mp4"
    subprocess.run([ffmpeg_path(), "-hide_banner", "-y", "-f", "lavfi",
                    "-i", "color=c=navy:s=320x240:d=12:r=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(mp4)], check=True, capture_output=True)
    vjob = DubJob(input=mp4, source_lang="en", target_lang="hu", engine="Piper",
                  output_dir=WORK, video_output_format="mp4",
                  burn_in=True, allow_video=True)
    vpipe = DubPipeline(vjob, log=log)
    vout = vpipe.run(
        WORK / "vjob", extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
        transcribe=lambda v: segs, translate=lambda x, s, t: x,
        synthesize=hu_synth, full=True,
    )
    log(f"DUBBED VIDEO: {vout} ({vout.stat().st_size} bytes)")
    assert vout.suffix == ".mp4" and vout.stat().st_size > 10000

    log(f"E2E GREEN in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
