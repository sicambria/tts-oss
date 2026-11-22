"""Music-robustness e2e: EN speech over a sine music bed.

Comparative gate (calibrated, not flaky): VAD-on must yield FEWER segments than
VAD-off on the same mixed clip, and zero segments fully inside the music-only
span. Uses real faster-whisper small (cached) + real ffmpeg; no NLLB/network.

Note: VAD is opt-in for spoken-only content. For SUNG vocals the default is
VAD-off — Silero VAD drops sung lines along with the music (proven on a real
238 s song: VAD-on kept 5/52 segments). This test guards the VAD path itself.
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "output" / "e2e_dub_music"


def _write_speech_wav(path: Path, text: str = "Hello world. This is a dubbing test.") -> Path:
    from app import PiperService
    from app import SynthesisRequest
    piper = PiperService(print)
    req = SynthesisRequest(text=text, language="en", output_file=path, engine="Piper",
                           piper_voice_label="en_US-lessac-medium",
                           piper_voice_code="en_US-lessac-medium",
                           speaker_name="", speaker_wav="", speed=1.0)
    return Path(piper.synthesize(req))


def main() -> int:
    from dubbing import ffmpeg_path
    WORK.mkdir(parents=True, exist_ok=True)
    print("[e2e-music] synth speech…", flush=True)
    speech = _write_speech_wav(WORK / "speech.wav")
    with wave.open(str(speech), "rb") as wf:
        rate, n = wf.getframerate(), wf.getnframes()
    speech_dur = n / float(rate)
    total = speech_dur + 6.0  # 3 s music lead + 3 s tail
    print(f"[e2e-music] speech {speech_dur:.1f}s, total {total:.1f}s", flush=True)
    mixed = WORK / "mixed.wav"
    # Music bed under everything + speech delayed past the 3 s lead-in.
    cmd = [ffmpeg_path(), "-hide_banner", "-y",
           "-f", "lavfi", "-i", f"sine=frequency=220:duration={total:.1f}",
           "-i", str(speech),
           "-filter_complex",
           "[0:a]volume=0.4[bed];[1:a]adelay=3000|3000[sp];[bed][sp]amix=inputs=2:duration=longest",
           "-ar", "16000", "-ac", "1", str(mixed)]
    subprocess.run(cmd, check=True, capture_output=True)
    from dubbing.stages import transcribe
    print("[e2e-music] transcribe VAD-off…", flush=True)
    segs_off = transcribe(mixed, "small", language="en", vad_filter=False)
    print(f"[e2e-music] VAD-off: {len(segs_off)} segs", flush=True)
    print("[e2e-music] transcribe VAD-on…", flush=True)
    segs_on = transcribe(mixed, "small", language="en", vad_filter=True)
    print(f"[e2e-music] VAD-on: {len(segs_on)} segs", flush=True)
    for s in segs_on:
        print(f"  [{s.start:.1f}-{s.end:.1f}] {s.text[:100]}", flush=True)
    music_only = [s for s in segs_on if s.end <= 2.5 or s.start >= 3.0 + speech_dur + 0.5]
    print(f"[e2e-music] VAD-off={len(segs_off)} VAD-on={len(segs_on)} "
          f"music-only={len(music_only)}", flush=True)
    assert segs_on, "VAD-on lost all speech"
    assert len(segs_on) <= len(segs_off), "VAD made segmentation worse"
    assert not music_only, f"VAD-on still hallucinates in music-only span: {music_only}"
    print("[e2e-music] GREEN", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
