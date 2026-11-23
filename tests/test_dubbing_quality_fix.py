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
    assert seen["kwargs"].get("temperature") == 0.0
    assert seen["kwargs"].get("hallucination_silence_threshold") == 2.0
    assert seen["kwargs"].get("log_prob_threshold") == -2.0
    assert seen["kwargs"].get("no_speech_threshold") == 1.0


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
            seen["norepeat"] = kwargs.get("no_repeat_ngram_size")
            seen["reppen"] = kwargs.get("repetition_penalty")
            return [[1]]

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda _i: fake_tok),
        AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=lambda _i: FakeModel()),
    ))
    segs = stages_mod.translate_segments([Segment(0.0, 1.0, text="hello world")], "en", "hu")
    assert segs[0].translated == "Szia világ"
    assert fake_tok.src_lang == "eng_Latn"
    assert seen["bos"] == "hun_Latn" and seen["forced"] == 999
    assert seen["norepeat"] == 3 and seen["reppen"] == 1.2


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
    vocal = tmp_path / "clip_(Vocals)_Kim_Vocal_2.wav"
    inst = tmp_path / "clip_(Instrumental)_Kim_Vocal_2.wav"
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
    # Order-independent: instrumental first must not win (model suffix
    # "Kim_Vocal_2" contains "vocal" and matches every stem).
    v2, b2 = stages_mod._pick_vocal_bg(tmp_path, [str(inst), str(vocal)], tmp_path / "fallback.wav")
    assert v2 == vocal and b2 == inst


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
    assert res["vocal_coverage"] == 1.0
    # Empty translation fails:
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n\n", encoding="utf-8")
    res2 = check(tmp_path)
    assert res2["ok"] is False


def test_fit_never_stretches(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    wav = _tiny_wav(tmp_path / "short.wav", seconds=1.0)
    monkeypatch.setattr(stages_mod, "_ffmpeg", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("ffmpeg must not run for short dubs")))
    out, overflow = stages_mod.fit_to_slot(wav, 5.0, tmp_path)
    assert out == wav and overflow is False


def test_fit_mild_squeeze_and_spill_cap(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    seen: dict = {}
    wav = _tiny_wav(tmp_path / "long.wav", seconds=2.6)

    def fake_ffmpeg(*args, **kwargs):
        seen["args"] = args
        (tmp_path / "long_fit.wav").write_bytes(b"x")

    monkeypatch.setattr(stages_mod, "_ffmpeg", fake_ffmpeg)
    # r=1.3 -> squeeze to fit, no overflow
    out, overflow = stages_mod.fit_to_slot(wav, 2.0, tmp_path)
    assert out != wav and overflow is False
    assert "atempo=" in " ".join(str(a) for a in seen["args"])
    # r=3.0 -> squeeze capped at 1.5 (spill), overflow flagged
    out2, overflow2 = stages_mod.fit_to_slot(wav, 2.6 / 3.0, tmp_path)
    assert overflow2 is True
    filt = " ".join(str(a) for a in seen["args"])
    assert "atempo=1.5" in filt


def test_merge_short_segments():
    from dubbing.config import Segment
    from dubbing.stages import merge_short_segments
    assert merge_short_segments([]) == []
    segs = [Segment(0.0, 1.0, text="a"), Segment(1.0, 1.4, text="b"),
            Segment(5.0, 7.0, text="c")]
    merged = merge_short_segments(segs)
    assert len(merged) == 2
    assert merged[0].text == "a b" and merged[0].start == 0.0 and merged[0].end == 1.4
    assert merged[1].text == "c"
    # chain of micros collapses into singable chunks (no 45 s mega-phrase)
    chain = [Segment(float(i), float(i) + 0.5, text=f"w{i}") for i in range(5)]
    merged_chain = merge_short_segments(chain)
    assert len(merged_chain) == 2
    assert max(s.duration for s in merged_chain) <= 12.0
    # long spans never fuse into mega-phrases (12 s cap)
    long_chain = [Segment(float(i), float(i) + 1.0, text=f"w{i}") for i in range(20)]
    merged_long = merge_short_segments(long_chain)
    assert len(merged_long) > 1
    assert max(s.duration for s in merged_long) <= 12.0
    # long segments with wide gaps never merge
    spaced = [Segment(0.0, 3.0, text="x"), Segment(5.0, 8.0, text="y")]
    assert len(merge_short_segments(spaced)) == 2


def test_separate_cli_fallback(tmp_path, monkeypatch):
    import subprocess as _sp

    from dubbing import stages as stages_mod
    monkeypatch.setitem(sys.modules, "audio_separator.separator", None)
    # force in-process import to fail even if package exists
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("audio_separator"):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(stages_mod, "_separator_cli",
                        lambda: tmp_path / "audio-separator")
    monkeypatch.setattr(stages_mod, "_pick_vocal_bg",
                        lambda td, names, fb: (tmp_path / "vocals.wav", tmp_path / "bg.wav"))
    (tmp_path / "vocals.wav").write_bytes(b"v")
    (tmp_path / "bg.wav").write_bytes(b"b")

    def fake_run(cmd, **kwargs):
        assert "--model_filename" in cmd
        return _sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_sp, "run", fake_run)
    vocal, bg = stages_mod.separate_background(tmp_path / "in.wav", tmp_path, True)
    assert vocal.name == "vocals.wav" and bg is not None and bg.name == "bg.wav"


def test_defuse_repetition():
    from dubbing.stages import defuse_repetition as d
    assert d("Say one, " + ", ".join(["ma'am"] * 30)) == "Say one, ma'am, ma'am,"
    assert d("Mondd, mikor. Mondd, mikor.") == "Mondd, mikor. Mondd, mikor."
    assert d("hello world") == "hello world"
    assert d("") == ""
    assert d("Pretty please. Pretty please. Say when. Say when.") == \
        "Pretty please. Pretty please. Say when. Say when."


def test_vocal_coverage(tmp_path):
    import wave

    from dubbing.quality import vocal_coverage
    srt = tmp_path / "dub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nSzia\n\n"
                   "2\n00:00:01,000 --> 00:00:02,000\nSzia\n", encoding="utf-8")
    _tiny_wav(tmp_path / "dub_timeline.wav", seconds=2.0)
    cov = vocal_coverage(tmp_path)
    assert cov == {"ratio": 1.0, "silent": [], "total": 2}
    # silence the second span
    import struct
    with wave.open(str(tmp_path / "dub_timeline.wav"), "rb") as wf:
        params, frames = wf.getparams(), wf.readframes(wf.getnframes())
    half = len(frames) // 2
    with wave.open(str(tmp_path / "dub_timeline.wav"), "wb") as wf:
        wf.setparams(params)
        wf.writeframes(frames[:half] + struct.pack("<%dh" % (half // 2), *([0] * (half // 2))))
    cov2 = vocal_coverage(tmp_path)
    assert cov2["ratio"] == 0.5 and cov2["silent"] == [1]


def test_duck_envelope_shape():
    from dubbing.stages import duck_envelope
    env = duck_envelope(10.0, 100, [(4.0, 6.0)], 0.2, 1.0)
    assert abs(env[0] - 1.0) < 1e-9 and abs(env[-1] - 1.0) < 1e-9
    assert abs(env[500] - 0.2) < 1e-9  # hold region
    # ramp down monotonic, ramp up monotonic
    down = env[350:400]
    assert all(b <= a + 1e-9 for a, b in zip(down, down[1:]))
    up = env[600:690]
    assert all(b >= a - 1e-9 for a, b in zip(up, up[1:]))
    assert min(env) >= 0.2 - 1e-9 and max(env) <= 1.0 + 1e-9


def _burst_wav(path, spans, freq=440.0, seconds=4.0, rate=16000):
    import math
    import struct
    import wave
    n = int(seconds * rate)
    frames = []
    for i in range(n):
        t = i / rate
        on = any(a <= t < b for a, b in spans)
        v = int(10000 * math.sin(2 * math.pi * freq * t)) if on else 0
        frames.append(v)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack("<%dh" % n, *frames))
    return path


def _rms_of(wav_path, a, b):
    import math
    import struct
    import wave
    with wave.open(str(wav_path), "rb") as wf:
        rate, n, ch = wf.getframerate(), wf.getnframes(), wf.getnchannels()
        raw = wf.readframes(n)
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    mono = s[0::ch] if ch > 1 else s  # deinterleave: time->frame indexing
    win = mono[int(a * rate):int(b * rate)]
    return math.sqrt(sum(v * v for v in win) / len(win)) / 32768 if win else 0.0


def test_mix_ducked_levels(tmp_path):
    from dubbing import stages as stages_mod
    bg = _tiny_wav(tmp_path / "bg.wav", seconds=4.0, rate=16000, freq=220.0)
    out = tmp_path / "mix.wav"
    # silent dub isolates the bed: gap must stay full, span ducked to 0.2
    silent = _burst_wav(tmp_path / "sil.wav", [], freq=880.0)
    stages_mod.mix_with_bg(silent, bg, 0.2, out, spans=[(1.0, 2.0)], gap_level=1.0)
    bg_rms = _rms_of(bg, 0, 4)
    assert abs(_rms_of(out, 0.1, 0.6) - bg_rms) / bg_rms < 0.05
    assert abs(_rms_of(out, 1.2, 1.8) - 0.2 * bg_rms) / (0.2 * bg_rms) < 0.10
    # duck off / unset falls back to legacy static path
    out2 = tmp_path / "mix2.wav"
    stages_mod.mix_with_bg(silent, bg, 0.2, out2)
    assert abs(_rms_of(out2, 1.2, 1.8) - 0.2 * bg_rms) / (0.2 * bg_rms) < 0.10
    assert abs(_rms_of(out2, 0.1, 0.6) - 0.2 * bg_rms) / (0.2 * bg_rms) < 0.10


def test_truncation_audit(tmp_path):
    import json

    from dubbing.quality import check
    srt = tmp_path / "dub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nRövid\n", encoding="utf-8")
    _tiny_wav(tmp_path / "dub_timeline.wav", seconds=5.0)
    (tmp_path / "dub_transcript.json").write_text(json.dumps(
        [{"start": 0.0, "end": 5.0,
          "text": "This is a long English source sentence that got cut",
          "translated": "Rövid"}]), encoding="utf-8")
    res = check(tmp_path)
    assert res["ok"] is False
    assert any("truncat" in f for f in res["failures"])


def test_config_bg_fields(tmp_path):
    import pytest

    from dubbing.config import DubJob
    job = DubJob(input=tmp_path / "a.mp3")
    assert job.bg_gap_ratio == 1.0 and job.bg_duck is True and job.keep_bg_ratio == 0.5
    job.validate()
    with pytest.raises(ValueError, match="bg_gap_ratio"):
        DubJob(input=tmp_path / "a.mp3", bg_gap_ratio=1.5).validate()


def test_pct_helper():
    from dubbing.ui_wizard import _pct
    assert _pct(0.5) == 50.0
    assert _pct("bad") == 50.0
    assert _pct(2.0) == 100.0
    assert _pct(-1.0) == 0.0


def test_pipeline_passes_spans_when_ducking(tmp_path, monkeypatch):
    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    for duck, gap in ((True, 1.0), (False, 1.0)):
        job = DubJob(input=tmp_path / "a.mp3", target_lang="hu",
                     output_dir=tmp_path / "out", separation_enabled=True,
                     bg_duck=duck, keep_bg_ratio=0.5, bg_gap_ratio=gap)
        job.output_dir.mkdir(exist_ok=True)
        seen: dict = {}

        def fake_mix(dub, bg, ratio, out, spans=None, gap_level=None):
            seen["spans"] = spans
            seen["gap"] = gap_level
            out.write_bytes(b"mix")
            return out

        monkeypatch.setattr(stages_mod, "separate_background",
                            lambda wav, tmp, en: (wav, tmp / "bg.wav"))
        monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
        monkeypatch.setattr(stages_mod, "concat_timeline",
                            lambda placed, total, out: (out.write_bytes(b"mix"), out)[1])
        monkeypatch.setattr(stages_mod, "mix_with_bg", fake_mix)
        monkeypatch.setattr(stages_mod, "export_audio",
                            lambda wav, out, bitrate="192k": (out.write_bytes(b"mp3"), out)[1])
        (tmp_path / "bg.wav").write_bytes(b"x")
        pipe = DubPipeline(job, log=lambda m: None)
        out = pipe.run(tmp_path,
                       extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                       transcribe=lambda v: [Segment(0.0, 1.0, text="hi")],
                       translate=lambda segs, s, t: (setattr(segs[0], "translated", "szia"), segs)[1],
                       synthesize=lambda text, hint: hint, full=True)
        assert out.suffix == ".mp3"
        if duck:
            assert seen["spans"] == [(0.0, 1.0)] and seen["gap"] == gap
        else:
            assert seen["spans"] is None and seen["gap"] is None
