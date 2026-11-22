"""Fill remaining coverage: mocked ffmpeg paths, fake ML modules, cyhunspell backend."""
from __future__ import annotations

import struct
import sys
import types
import wave
from pathlib import Path


def _tiny_wav(path: Path, seconds: float = 1.0) -> Path:
    nframes = int(seconds * 44100)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(struct.pack("<%dh" % nframes, *([0] * nframes)))
    return path


def test_extract_success_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    out = stages_mod.extract_audio(tmp_path / "in.mp3", tmp_path / "out.wav")
    assert out == tmp_path / "out.wav"


def test_export_all_formats_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    for ext in (".wav", ".mp3", ".ogg"):
        assert stages_mod.export_audio(tmp_path / "a.wav", tmp_path / f"out{ext}") == tmp_path / f"out{ext}"


def test_fit_squeeze_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    wav = _tiny_wav(tmp_path / "two.wav", seconds=2.0)
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    out, overflow = stages_mod.fit_to_slot(wav, 1.0, tmp_path)
    assert overflow is False and out.name.endswith("_fit.wav")


def test_mix_with_bg_mocked(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: None)
    out = stages_mod.mix_with_bg(tmp_path / "d.wav", tmp_path / "b.wav", 0.2, tmp_path / "m.wav")
    assert out == tmp_path / "m.wav"


def test_transcribe_success_fake_module(tmp_path, monkeypatch):
    import types as _t

    from dubbing import stages as stages_mod
    seg = _t.SimpleNamespace(start=0.0, end=1.0, text="hi")
    fake_model = _t.SimpleNamespace(transcribe=lambda path, word_timestamps=True: ([seg], {}))
    fake_mod = _t.SimpleNamespace(WhisperModel=lambda *a, **k: fake_model)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
    segs = stages_mod.transcribe(tmp_path / "v.wav")
    assert len(segs) == 1 and segs[0].text == "hi"


def test_translate_load_failure(monkeypatch, tmp_path):
    import pytest

    from dubbing import stages as stages_mod
    from dubbing.config import Segment
    fake_mod = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda _id: (_ for _ in ()).throw(RuntimeError("no net"))),
        AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=lambda _id: None),
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_mod)
    with pytest.raises(RuntimeError, match="Could not load"):
        stages_mod.translate_segments([Segment(0.0, 1.0, text="hi")])


def _fake_hunspell(monkeypatch, spell_result: bool = False, suggest_raises: bool = False):
    class FakeHandle:
        def __init__(self, *a):
            pass

        def spell(self, word):
            return spell_result

        def suggest(self, word):
            if suggest_raises:
                raise RuntimeError("no sug")
            return ["sug1", "sug2", "sug3", "sug4", "sug5", "sug6"]

    monkeypatch.setitem(sys.modules, "hunspell", types.SimpleNamespace(HunSpell=FakeHandle))


def test_cyhunspell_backend_paths(monkeypatch):
    from dubbing import spellcheck as spellcheck_mod
    _fake_hunspell(monkeypatch, spell_result=False)
    monkeypatch.setattr(spellcheck_mod, "_spylls_available", lambda: False)
    assert spellcheck_mod._cyhunspell_available() is True
    spellcheck_mod._BACKEND = None
    try:
        assert spellcheck_mod.backend() == "cyhunspell"
        assert spellcheck_mod.available("hu_HU") is True
        hits = spellcheck_mod.check("hu_HU", "helyesiras")
        assert hits and hits[0][0] == "helyesiras" and len(hits[0][1]) == 5
    finally:
        spellcheck_mod._BACKEND = None


def test_cyhunspell_spell_true_and_unavailable(monkeypatch):
    from dubbing import spellcheck as spellcheck_mod
    _fake_hunspell(monkeypatch, spell_result=True)
    spellcheck_mod._BACKEND = "cyhunspell"
    try:
        assert spellcheck_mod.check("hu_HU", "helyes") == []
    finally:
        spellcheck_mod._BACKEND = None

    class BadHandle:
        def __init__(self, *a):
            raise RuntimeError("no dict")

    monkeypatch.setitem(sys.modules, "hunspell", types.SimpleNamespace(HunSpell=BadHandle))
    spellcheck_mod._BACKEND = "cyhunspell"
    try:
        assert spellcheck_mod.available("hu_HU") is False
        assert spellcheck_mod.check("hu_HU", "x") == []
    finally:
        spellcheck_mod._BACKEND = None


def test_spylls_suggest_fallback(monkeypatch):
    from dubbing import spellcheck as spellcheck_mod
    class FakeDict:
        def lookup(self, word):
            return False

        def suggest(self, word):
            raise RuntimeError("suggest broken")

    monkeypatch.setattr(spellcheck_mod, "_spylls_dictionary", lambda lang: FakeDict())
    spellcheck_mod._BACKEND = "spylls"
    try:
        hits = spellcheck_mod.check("hu_HU", "helyesiras")
        assert hits == [("helyesiras", [])]
    finally:
        spellcheck_mod._BACKEND = None
