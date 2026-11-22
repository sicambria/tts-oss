"""Stages unit tests — fast, hermetic (ffmpeg touched only via mocks or tiny wavs)."""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path


def _tiny_wav(path: Path, seconds: float = 1.0, rate: int = 44100) -> Path:
    import struct
    nframes = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack("<%dh" % nframes, *([0] * nframes)))
    return path


def test_atempo_chain_invalid_ratio():
    import pytest

    from dubbing.stages import atempo_chain
    with pytest.raises(ValueError):
        atempo_chain(0)
    assert atempo_chain(1.0) == [1.0]


def test_fit_to_slot_accept_band_no_ffmpeg(tmp_path):
    from dubbing.stages import fit_to_slot
    wav = _tiny_wav(tmp_path / "one.wav", seconds=1.0)
    out, overflow = fit_to_slot(wav, 1.0, tmp_path)
    assert out == wav and overflow is False


def test_fit_to_slot_bad_slot(tmp_path):
    from dubbing.stages import fit_to_slot
    wav = _tiny_wav(tmp_path / "one.wav", seconds=1.0)
    out, overflow = fit_to_slot(wav, 0.0, tmp_path)
    assert out == wav and overflow is True


def test_export_audio_bad_format(tmp_path):
    import pytest

    from dubbing.stages import export_audio
    with pytest.raises(ValueError):
        export_audio(tmp_path / "a.wav", tmp_path / "a.flac")


def test_concat_empty_raises(tmp_path):
    import pytest

    from dubbing.stages import concat_timeline
    with pytest.raises(ValueError):
        concat_timeline([], 1.0, tmp_path / "out.wav")


def test_concat_single_fast_path_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    wav = _tiny_wav(tmp_path / "one.wav", seconds=1.0)
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    out = stages_mod.concat_timeline([(wav, 0.0)], 1.0, tmp_path / "out.wav")
    assert out == tmp_path / "out.wav"


def test_concat_multi_mocked(tmp_path, monkeypatch):
    import subprocess as _subprocess

    from dubbing import stages as stages_mod
    wav = _tiny_wav(tmp_path / "one.wav", seconds=0.5)
    calls: list = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(_subprocess, "run", fake_run)
    out = stages_mod.concat_timeline([(wav, 0.0), (wav, 0.5)], 1.0, tmp_path / "out.wav")
    assert out == tmp_path / "out.wav" and calls


def test_mix_with_bg_none_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    wav = _tiny_wav(tmp_path / "dub.wav", seconds=0.5)
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    out = stages_mod.mix_with_bg(wav, None, 0.2, tmp_path / "mix.wav")
    assert out == tmp_path / "mix.wav"


def test_extract_failure_raises(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a, 1, "", "boom")
    monkeypatch.setattr(subprocess, "run", fake_run)
    import pytest
    with pytest.raises(RuntimeError):
        stages_mod.extract_audio(tmp_path / "in.mp3", tmp_path / "out.wav")


def test_separate_disabled_identity(tmp_path):
    from dubbing.stages import separate_background
    wav = tmp_path / "v.wav"
    wav.write_bytes(b"x")
    assert separate_background(wav, tmp_path, False) == (wav, None)


def test_separate_enabled_missing_dep(tmp_path):
    import pytest

    from dubbing.stages import separate_background
    with pytest.raises(RuntimeError, match="audio-separator"):
        separate_background(tmp_path / "v.wav", tmp_path, True)


def test_transcribe_missing_dep(monkeypatch, tmp_path):
    from dubbing import stages as stages_mod
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    import pytest
    with pytest.raises(RuntimeError, match="faster-whisper"):
        stages_mod.transcribe(tmp_path / "v.wav")


def test_translate_with_fake_transformers(monkeypatch, tmp_path):
    import types

    from dubbing import stages as stages_mod
    from dubbing.config import Segment

    class FakeInputs(dict):
        def __getattr__(self, name):
            return self[name]

    class FakeTok:
        def __call__(self, text, **kwargs):
            return FakeInputs(input_ids=[1, 2])

        def convert_tokens_to_ids(self, tgt):
            return 1

        def batch_decode(self, gen, **kwargs):
            return ["szia"]

    fake_mod = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda _id: FakeTok()),
        AutoModelForSeq2SeqLM=types.SimpleNamespace(
            from_pretrained=lambda _id: types.SimpleNamespace(generate=lambda **k: [[1]])
        ),
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_mod)
    segs = stages_mod.translate_segments([Segment(0.0, 1.0, text="hello")])
    assert segs[0].translated == "szia"
