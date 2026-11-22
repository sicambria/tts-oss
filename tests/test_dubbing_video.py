"""Video mux + package probe + spellcheck edge tests (mocked, no models)."""
from __future__ import annotations

import subprocess
import sys


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
