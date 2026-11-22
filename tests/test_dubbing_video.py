"""Video mux + package probe + spellcheck edge tests (mocked, no models)."""
from __future__ import annotations

import subprocess
import sys


def _capture_cmd(monkeypatch, libass_ok: bool = True) -> list:
    import dubbing.video as video_mod
    seen: list = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video_mod, "has_libass", lambda: libass_ok)
    monkeypatch.setattr(video_mod, "subprocess",
                        __import__("types").SimpleNamespace(run=fake_run))
    return seen


def _maps(cmd: list, *wanted: str) -> bool:
    flat = [str(p) for p in cmd]
    for i in range(len(flat) - len(wanted) + 1):
        if flat[i:i + len(wanted)] == list(wanted):
            return True
    return False


def test_mux_burn_maps_dub_audio(tmp_path, monkeypatch):
    """Regression: the burn-in path once shipped the ORIGINAL audio because
    ffmpeg's automatic stream selection ignores the dub wav without -map."""
    from dubbing.video import mux_video
    seen = _capture_cmd(monkeypatch, libass_ok=True)
    mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
              tmp_path / "out.mp4", True)
    assert _maps(seen[0], "-map", "0:v:0"), seen[0]
    assert _maps(seen[0], "-map", "1:a:0"), seen[0]


def test_mux_softsub_maps_dub_audio(tmp_path, monkeypatch):
    from dubbing.video import mux_video
    seen = _capture_cmd(monkeypatch, libass_ok=True)
    mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
              tmp_path / "out.mp4", False)
    assert _maps(seen[0], "-map", "0:v:0"), seen[0]
    assert _maps(seen[0], "-map", "1:a:0"), seen[0]
    assert _maps(seen[0], "-map", "2:0"), seen[0]


def _tone_wav(path, freq: float, seconds: float = 2.0, rate: int = 16000):
    import math
    import struct
    import wave
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack("<%dh" % n,
                                   *[int(10000 * math.sin(2 * math.pi * freq * i / rate))
                                     for i in range(n)]))
    return path


def test_mux_burn_audio_is_dub_integration(tmp_path):
    """End-to-end proof with real ffmpeg: 440 Hz source + 880 Hz dub must
    yield 880 Hz in the output (this exact repro caught the English-audio bug)."""
    from dubbing import ffmpeg_path
    from dubbing.quality import mux_audit
    from dubbing.video import mux_video
    ff = ffmpeg_path()
    src = tmp_path / "src.mp4"
    r = subprocess.run([ff, "-hide_banner", "-y", "-f", "lavfi",
                        "-i", "color=c=red:s=160x120:d=2:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(src)], capture_output=True)
    assert r.returncode == 0
    dub = _tone_wav(tmp_path / "dub.wav", 880.0)
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nE\n", encoding="utf-8")
    try:
        from dubbing import has_libass
        if not has_libass():
            import pytest
            pytest.skip("libass missing")
    except Exception:
        pass
    for burn in (True, False):
        out = tmp_path / f"out_{int(burn)}.mp4"
        mux_video(src, dub, srt, out, burn)
        audit = mux_audit(out, dub)
        assert audit["ok"], (burn, audit)


def test_mux_audit_rejects_original_audio(tmp_path):
    """mux_audit must FAIL when the deliverable carries the wrong track."""
    from dubbing import ffmpeg_path
    from dubbing.quality import mux_audit
    ff = ffmpeg_path()
    src = tmp_path / "src.mp4"
    r = subprocess.run([ff, "-hide_banner", "-y", "-f", "lavfi",
                        "-i", "color=c=red:s=160x120:d=2:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(src)], capture_output=True)
    assert r.returncode == 0
    other = _tone_wav(tmp_path / "other.wav", 880.0)
    audit = mux_audit(src, other)
    assert not audit["ok"], audit


def test_mux_refuses_existing_output(tmp_path):
    from dubbing.video import mux_video
    out = tmp_path / "out.mp4"
    out.write_bytes(b"x")
    import pytest
    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt", out, False)


def test_mux_burn_needs_libass(tmp_path, monkeypatch):
    import dubbing.video as video_mod
    monkeypatch.setattr(video_mod, "has_libass", lambda: False)
    import pytest
    with pytest.raises(RuntimeError, match="libass"):
        video_mod.mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
                            tmp_path / "out.mp4", True)


def test_mux_softsub_success_mocked(tmp_path, monkeypatch):
    import dubbing.video as video_mod
    monkeypatch.setattr(video_mod, "subprocess",
                        __import__("types").SimpleNamespace(
                            run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")))
    out = video_mod.mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
                              tmp_path / "out.mp4", False)
    assert out == tmp_path / "out.mp4"


def test_mux_burn_success_mocked(tmp_path, monkeypatch):
    import types

    import dubbing.video as video_mod
    monkeypatch.setattr(video_mod, "has_libass", lambda: True)
    seen: list = []
    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(video_mod, "subprocess", types.SimpleNamespace(run=fake_run))
    out = video_mod.mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
                              tmp_path / "out.mp4", True)
    assert out == tmp_path / "out.mp4"
    assert any("subtitles=" in str(part) for part in seen[0])


def test_mux_failure_raises(tmp_path, monkeypatch):
    import types

    import dubbing.video as video_mod
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "mux boom")
    monkeypatch.setattr(video_mod, "subprocess", types.SimpleNamespace(run=fake_run))
    import pytest
    with pytest.raises(RuntimeError, match="Video mux failed"):
        video_mod.mux_video(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "s.srt",
                            tmp_path / "out.mp4", False)


def test_probes_and_helpers():
    from dubbing import CYHUNSPELL_SUDO_HINT
    from dubbing import is_cyhunspell_build_failure
    from dubbing import is_video_input
    from dubbing import pip_missing_specs
    assert is_video_input("a.mp4") is True
    assert is_video_input("a.mp3") is False
    assert "sudo" in CYHUNSPELL_SUDO_HINT
    assert is_cyhunspell_build_failure("autoreconf autopoint failed") is True
    assert is_cyhunspell_build_failure("all good") is False
    specs = pip_missing_specs(True)
    assert any("audio-separator" in s for s in specs)


def test_has_probes_false_paths(monkeypatch):
    import dubbing
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "audio_separator", None)
    assert dubbing.has_faster_whisper() is False
    assert dubbing.has_separator() is False


def test_spellcheck_no_backend(monkeypatch):
    from dubbing import spellcheck as spellcheck_mod
    monkeypatch.setattr(spellcheck_mod, "_spylls_available", lambda: False)
    monkeypatch.setattr(spellcheck_mod, "_cyhunspell_available", lambda: False)
    spellcheck_mod._BACKEND = None
    try:
        assert spellcheck_mod.backend() is None
        assert spellcheck_mod.available("hu_HU") is False
        assert spellcheck_mod.check("hu_HU", "hello") == []
        assert spellcheck_mod.check("hu_HU", "   ") == []
        assert spellcheck_mod.find_dictionary("xx_XX") is None
    finally:
        spellcheck_mod._BACKEND = None


def test_unique_output(tmp_path):
    from dubbing.pipeline import unique_output
    base = tmp_path / "dub.mp3"
    assert unique_output(base) == base
    base.write_bytes(b"x")
    alt = unique_output(base)
    assert alt != base and alt.suffix == ".mp3"


def test_pipeline_full_no_synthesizer(tmp_path):
    import pytest

    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp3", target_lang="hu")
    pipe = DubPipeline(job, log=lambda m: None)
    with pytest.raises(RuntimeError, match="TTS synthesizer"):
        pipe.run(tmp_path,
                 extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                 transcribe=lambda v: [Segment(0.0, 1.0, text="hi")],
                 translate=lambda segs, s, t: segs,
                 full=True)


def test_pipeline_overflow_flagged(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp3", target_lang="hu",
                 output_dir=tmp_path / "out")
    job.output_dir.mkdir()
    logs: list[str] = []
    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, True))
    monkeypatch.setattr(stages_mod, "concat_timeline",
                        lambda placed, total, out: (out.write_bytes(b"x"), out)[1])
    monkeypatch.setattr(stages_mod, "mix_with_bg",
                        lambda dub, bg, ratio, out: (out.write_bytes(b"x"), out)[1])
    monkeypatch.setattr(stages_mod, "export_audio",
                        lambda wav, out, bitrate="192k": (out.write_bytes(b"x"), out)[1])

    def fake_synth(text, hint: _Path) -> _Path:
        hint.write_bytes(b"w")
        return hint

    pipe = DubPipeline(job, log=logs.append)
    out = pipe.run(tmp_path,
                   extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                   transcribe=lambda v: [Segment(0.0, 0.5, text="hi")],
                   translate=lambda segs, s, t: segs,
                   synthesize=fake_synth, full=True)
    assert out.is_file()
    assert job.segments[0].overflow is True
    assert any("overflow" in m.lower() for m in logs)


def test_pipeline_video_success_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp4", target_lang="hu",
                 output_dir=tmp_path / "out", allow_video=True)
    job.output_dir.mkdir()
    monkeypatch.setattr("dubbing.video.mux_video",
                        lambda video, audio, srt, out, burn: (out.write_bytes(b"v"), out)[1])
    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
    monkeypatch.setattr(stages_mod, "concat_timeline",
                        lambda placed, total, out: (out.write_bytes(b"x"), out)[1])
    monkeypatch.setattr(stages_mod, "mix_with_bg",
                        lambda dub, bg, ratio, out: (out.write_bytes(b"x"), out)[1])
    pipe = DubPipeline(job, log=lambda m: None)
    out = pipe.run(tmp_path,
                   extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                   transcribe=lambda v: [Segment(0.0, 0.5, text="hi")],
                   translate=lambda segs, s, t: segs,
                   synthesize=lambda text, hint: (hint.write_bytes(b"w"), hint)[1],
                   full=True)
    assert out.suffix == ".mp4" and out.is_file()


def test_spellcheck_check_empty_text():
    from dubbing import spellcheck as spellcheck_mod
    assert spellcheck_mod.check("hu_HU", "   ") == []
