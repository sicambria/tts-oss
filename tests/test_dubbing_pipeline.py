"""Spellcheck + pipeline math (mocked, no network)."""

from dubbing import stages


def test_spellcheck_missing_lib_noop(monkeypatch):
    import dubbing.spellcheck as spellcheck_mod
    monkeypatch.setattr(spellcheck_mod, "_BACKEND", "")
    monkeypatch.setattr("dubbing.spellcheck._spylls_available", lambda: False)
    monkeypatch.setattr("dubbing.spellcheck._cyhunspell_available", lambda: False)
    spellcheck_mod._BACKEND = None
    assert spellcheck_mod.backend() is None
    assert spellcheck_mod.available("hu_HU") is False
    assert spellcheck_mod.check("hu_HU", "helyesiras") == []
    spellcheck_mod._BACKEND = None


def test_spellcheck_spylls_hu():
    from dubbing import spellcheck as spellcheck_mod
    if spellcheck_mod.find_dictionary("hu_HU") is None:
        import pytest
        pytest.skip("no hu_HU dictionary on this machine")
    try:
        import spylls  # noqa: F401
    except Exception:
        import pytest
        pytest.skip("spylls not installed")
    spellcheck_mod._BACKEND = None
    try:
        assert spellcheck_mod.available("hu_HU") is True
        hits = spellcheck_mod.check("hu_HU", "Ez egy helyesiras teszt")
        words = [w for w, _ in hits]
        assert "helyesiras" in words
    finally:
        spellcheck_mod._BACKEND = None


def test_atempo_chain_vectors():
    assert stages.atempo_chain(3.0) == [2.0, 1.5]
    assert stages.atempo_chain(0.2) == [0.5, 0.5, 0.8]
    assert stages.atempo_chain(5.0) == [2.0, 2.0, 1.25]
    assert stages.atempo_chain(1.0) == [1.0]


def test_pipeline_order_mocked(tmp_path):
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    calls: list[str] = []
    job = DubJob(input=tmp_path / "a.mp3", target_lang="hu")

    def fake_extract(src, dst):
        calls.append("extract")
        dst.write_bytes(b"x")
        return dst

    def fake_transcribe(vocal):
        calls.append("transcribe")
        return [Segment(0.0, 1.0, text="hello")]

    def fake_translate(segs, src, tgt):
        calls.append("translate")
        segs[0].translated = "szia"
        return segs

    pipe = DubPipeline(job, log=lambda m: None)
    srt = pipe.run(tmp_path, extract=fake_extract, transcribe=fake_transcribe,
                   translate=fake_translate)
    assert calls == ["extract", "transcribe", "translate"]
    assert srt.is_file()
