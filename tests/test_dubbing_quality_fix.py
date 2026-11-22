"""New-behavior tests for the HU-dub quality fix (mocked, no network/models)."""
from __future__ import annotations

import sys
import types
import wave
from pathlib import Path


def _tiny_wav(path: Path, seconds: float = 1.0, rate: int = 16000, freq: float = 440.0) -> Path:
    import math
    import struct
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = [int(10000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
        wf.writeframes(struct.pack("<%dh" % n, *frames))
    return path


def test_lang_mappers():
    from dubbing.stages import nllb_code
    from dubbing.stages import whisper_lang
    assert nllb_code("en") == "eng_Latn"
    assert nllb_code("hu") == "hun_Latn"
    assert nllb_code("eng_Latn") == "eng_Latn"
    assert nllb_code("hun_Latn") == "hun_Latn"
    assert whisper_lang("eng_Latn") == "en"
    assert whisper_lang("hun_Latn") == "hu"
    assert whisper_lang("en") == "en"
    assert whisper_lang(None) is None


def test_transcribe_passes_vad_and_language(monkeypatch, tmp_path):
    import dubbing.stages as stages_mod
    seen: dict = {}

    class FakeSeg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text = s, e, t

    class FakeModel:
        def __init__(self, *a, **k):
            seen["init"] = (a, k)

        def transcribe(self, audio, **kwargs):
            seen["kwargs"] = kwargs
            return ([FakeSeg(0.0, 1.0, " hello ")], None)

    monkeypatch.setitem(sys.modules, "faster_whisper",
                        types.SimpleNamespace(WhisperModel=FakeModel))
    wav = _tiny_wav(tmp_path / "v.wav")
    segs = stages_mod.transcribe(wav, "small", language="eng_Latn", vad_filter=True)
    assert segs and segs[0].text == "hello"
    assert seen["kwargs"].get("language") == "en"
    assert seen["kwargs"].get("vad_filter") is True
    assert seen["kwargs"].get("condition_on_previous_text") is False


def test_translate_sets_src_lang_and_bos(monkeypatch):
    import dubbing.stages as stages_mod
    from dubbing.config import Segment
    seen: dict = {}

    class FakeInputs(dict):
        def __getattr__(self, name):
            return self[name]

    class FakeTok:
        src_lang = None

        def __call__(self, text, **kwargs):
            return FakeInputs(input_ids=[[1, 2, 3]])

        def convert_tokens_to_ids(self, code):
            seen["bos"] = code
            return 999

        def batch_decode(self, gen, **kwargs):
            return ["Szia világ"]

    fake_tok = FakeTok()

    class FakeModel:
        def generate(self, **kwargs):
            seen["forced"] = kwargs.get("forced_bos_token_id")
            return [[1]]

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda _i: fake_tok),
        AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=lambda _i: FakeModel()),
    ))
    segs = stages_mod.translate_segments([Segment(0.0, 1.0, text="hello world")], "en", "hu")
    assert segs[0].translated == "Szia világ"
    assert fake_tok.src_lang == "eng_Latn"
    assert seen["bos"] == "hun_Latn" and seen["forced"] == 999


def test_translate_skips_empty(monkeypatch):
    import dubbing.stages as stages_mod
    from dubbing.config import Segment
    called = {"n": 0}

    class FakeInputs(dict):
        def __getattr__(self, name):
            return self[name]

    class FakeTok:
        src_lang = None

        def __call__(self, text, **kwargs):
            return FakeInputs(input_ids=[[1]])

        def convert_tokens_to_ids(self, code):
            return 1

        def batch_decode(self, gen, **kwargs):
            called["n"] += 1
            return ["x"]

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda _i: FakeTok()),
        AutoModelForSeq2SeqLM=types.SimpleNamespace(
            from_pretrained=lambda _i: types.SimpleNamespace(generate=lambda **k: [[1]])),
    ))
    segs = stages_mod.translate_segments(
        [Segment(0.0, 1.0, text="  "), Segment(0.0, 1.0, text="hi")], "en", "hu")
    assert segs[0].translated == "" and segs[1].translated == "x"
    assert called["n"] == 1


def test_separate_real_impl_mocked(monkeypatch, tmp_path):
    import dubbing.stages as stages_mod
    vocal = tmp_path / "clip_Vocals.wav"
    inst = tmp_path / "clip_Instrumental.wav"
    vocal.write_bytes(b"v")
    inst.write_bytes(b"b")

    class FakeSep:
        def __init__(self, **kwargs):
            pass

        def load_model(self, **kwargs):
            pass

        def separate(self, wav):
            return [str(vocal), str(inst)]

    monkeypatch.setitem(sys.modules, "audio_separator.separator",
                        types.SimpleNamespace(Separator=FakeSep))
    import sys as _sys
    _sys.modules.pop("audio_separator.separator", None)
    # Patch via stages import hook: inject fake module path the code imports.
    monkeypatch.setitem(_sys.modules, "audio_separator",
                        types.SimpleNamespace(separator=types.SimpleNamespace(Separator=FakeSep)))
    # Direct unit of _pick_vocal_bg (no separator download):
    v, b = stages_mod._pick_vocal_bg(tmp_path, [str(vocal), str(inst)], tmp_path / "fallback.wav")
    assert v == vocal and b == inst


def test_pipeline_wires_bg_and_whisper(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    job = DubJob(input=tmp_path / "a.mp3", target_lang="hu", output_dir=tmp_path / "out",
                 separation_enabled=True, whisper_model="small", keep_bg_ratio=0.2)
    seen: dict = {}

    def fake_separate(wav, tmp, enabled):
        seen["separate_enabled"] = enabled
        bg = tmp / "bg.wav"
        bg.write_bytes(b"bg")
        return (wav, bg)

    def fake_transcribe(vocal, model_size="small", language=None, vad_filter=True):
        seen["transcribe"] = (model_size, language, vad_filter)
        return [Segment(0.0, 1.0, text="hello")]

    def fake_translate(segs, src, tgt):
        seen["translate"] = (src, tgt)
        for s in segs:
            s.translated = "szia"
        return segs

    def fake_synth(text, hint):
        p = hint.parent / "raw.wav"
        p.write_bytes(b"wav")
        return p

    monkeypatch.setattr(stages_mod, "separate_background", fake_separate)
    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
    monkeypatch.setattr(stages_mod, "concat_timeline",
                        lambda placed, total, out: (out.write_bytes(b"mix"), out)[1])

    def fake_mix(dub, bg, ratio, out):
        seen["mix_bg_none"] = bg is None
        out.write_bytes(b"mix")
        return out

    monkeypatch.setattr(stages_mod, "mix_with_bg", fake_mix)
    monkeypatch.setattr(stages_mod, "export_audio",
                        lambda wav, out, bitrate="192k": (out.write_bytes(b"mp3"), out)[1])
    pipe = DubPipeline(job, log=lambda m: None)
    out = pipe.run(tmp_path, extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                   transcribe=fake_transcribe, translate=fake_translate,
                   synthesize=fake_synth, full=True)
    assert out.suffix == ".mp3"
    assert seen["separate_enabled"] is True
    assert seen["transcribe"] == ("small", "en", False)
    assert seen["translate"] == ("en", "hu")
    assert seen["mix_bg_none"] is False


def test_config_new_fields_validate(tmp_path):
    import pytest

    from dubbing.config import DubJob
    job = DubJob(input=tmp_path / "a.mp3")
    job.validate()
    assert job.separation_enabled is False and job.whisper_model == "small"
    job2 = DubJob(input=tmp_path / "a.mp3", whisper_model="xxl")
    with pytest.raises(ValueError, match="whisper"):
        job2.validate()
    job3 = DubJob(input=tmp_path / "a.mp3", keep_bg_ratio=9.0)
    with pytest.raises(ValueError, match="keep_bg_ratio"):
        job3.validate()


def test_quality_gates(tmp_path):
    from dubbing.quality import check
    from dubbing.quality import repeated_ngram_ratio
    assert repeated_ngram_ratio(["hello world foo bar", "hello world foo bar"]) > 0.0
    srt = tmp_path / "dub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nSzia világ\n", encoding="utf-8")
    _tiny_wav(tmp_path / "dub_timeline.wav", seconds=2.0)
    res = check(tmp_path)
    assert res["segments"] == 1 and res["timeline_peak"] > 0.0
    # Empty translation fails:
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n\n", encoding="utf-8")
    res2 = check(tmp_path)
    assert res2["ok"] is False
