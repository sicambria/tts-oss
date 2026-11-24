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


def test_pipeline_full_mocked(tmp_path, monkeypatch):
    from pathlib import Path

    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp3", target_lang="hu", output_dir=tmp_path / "out")
    job.output_dir.mkdir()

    def fake_extract(src, dst):
        dst.write_bytes(b"x")
        return dst

    def fake_transcribe(vocal):
        return [Segment(0.0, 1.0, text="hello"), Segment(3.0, 4.0, text="bye")]

    def fake_translate(segs, src, tgt):
        for s in segs:
            s.translated = "szia"
        return segs

    made: list[Path] = []

    def fake_synth(text, hint):
        p = hint.parent / f"raw_{len(made)}.wav"
        p.write_bytes(b"wav")
        made.append(p)
        return p

    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
    monkeypatch.setattr(stages_mod, "concat_timeline", lambda placed, total, out: (out.write_bytes(b"mix"), out)[1])
    monkeypatch.setattr(stages_mod, "mix_with_bg", lambda dub, bg, ratio, out: (out.write_bytes(b"mix"), out)[1])
    monkeypatch.setattr(stages_mod, "export_audio", lambda wav, out, bitrate="192k": (out.write_bytes(b"mp3"), out)[1])

    pipe = DubPipeline(job, log=lambda m: None)
    out = pipe.run(tmp_path, extract=fake_extract, transcribe=fake_transcribe,
                   translate=fake_translate, synthesize=fake_synth, full=True)
    assert out.suffix == ".mp3" and out.is_file()
    assert len(made) == 2


def test_pipeline_full_video_allowed(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp4", target_lang="hu", allow_video=False,
                 output_dir=tmp_path / "out")
    job.output_dir.mkdir()
    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
    monkeypatch.setattr(stages_mod, "concat_timeline",
                        lambda placed, total, out: (out.write_bytes(b"mix"), out)[1])
    monkeypatch.setattr(stages_mod, "mix_with_bg",
                        lambda dub, bg, ratio, out, **kw: (out.write_bytes(b"mix"), out)[1])
    monkeypatch.setattr(stages_mod, "export_audio",
                        lambda wav, out, bitrate="192k": (out.write_bytes(b"mp3"), out)[1])
    import dubbing.video as video_mod
    monkeypatch.setattr(video_mod, "mux_video",
                        lambda video, audio, srt, out, burn, style=None: (out.write_bytes(b"mp4"), out)[1])
    pipe = DubPipeline(job, log=lambda m: None)
    out = pipe.run(tmp_path,
                   extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                   transcribe=lambda v: [Segment(0.0, 1.0, text="hi")],
                   translate=lambda segs, s, t: segs,
                   synthesize=lambda text, hint: hint,
                   full=True)
    assert out.suffix == ".mp4" and out.is_file()
