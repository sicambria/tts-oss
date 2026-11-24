"""Coverage fill for the push gate: ui_wizard helpers, quality gates, package utils."""
from __future__ import annotations

import struct
import sys
import types
import wave
from pathlib import Path


def _tiny_wav(path: Path, seconds: float = 1.0, rate: int = 16000, tone: bool = True) -> Path:
    import math
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        if tone:
            frames = [int(10000 * math.sin(2 * math.pi * 440.0 * i / rate)) for i in range(n)]
        else:
            frames = [0] * n
        wf.writeframes(struct.pack("<%dh" % n, *frames) if n else b"")
    return path


# ---- ui_wizard ----

def test_pct_invalid_and_dub_defaults_bad_ratio():
    from dubbing import ui_wizard as uw
    assert uw._pct(None) == 50.0
    assert uw._pct([1]) == 50.0
    d = uw.dub_defaults({"keep_bg_ratio": "bad", "bg_gap_ratio": None,
                         "source_lang": "xx", "target_lang": ""})
    assert d["keep_bg_ratio"] == 0.5
    assert d["bg_gap_ratio"] == 1.0
    assert d["source_lang"] == "en"
    assert d["target_lang"] == "hu"


def test_open_path_branches(monkeypatch):
    from dubbing import ui_wizard as uw
    calls = {}

    # win32
    import os as _os
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(_os, "startfile", lambda p: calls.setdefault("win", p), raising=False)
    uw.open_path("/tmp/x.mp4")
    assert calls.get("win") == "/tmp/x.mp4"

    # darwin
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(uw.subprocess, "Popen", lambda *a, **k: calls.setdefault("mac", a))
    uw.open_path("/tmp/y.mp4")
    assert calls["mac"][0] == ["open", "/tmp/y.mp4"]

    # linux
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(uw.subprocess, "Popen", lambda *a, **k: calls.setdefault("lin", a))
    uw.open_path("/tmp/z.mp4")
    assert calls["lin"][0] == ["xdg-open", "/tmp/z.mp4"]


class _FakeWindow:
    def __init__(self, fail_topmost: bool = False):
        self.calls = []
        self.fail_topmost = fail_topmost

    def deiconify(self):
        self.calls.append("deiconify")

    def lift(self):
        self.calls.append("lift")

    def attributes(self, *a):
        self.calls.append(("attributes", a))
        if self.fail_topmost and a[:2] == ("-topmost", True):
            raise RuntimeError("no wm")

    def update_idletasks(self):
        self.calls.append("update")
        raise RuntimeError("headless")


def test_file_dialog_top_success_and_cleanup():
    from dubbing import ui_wizard as uw
    win = _FakeWindow()
    seen = {}

    def fake_func(parent=None, **kw):
        seen["parent"] = parent
        seen["kw"] = kw
        return "/picked/file.mp4"

    out = uw._file_dialog_top(win, fake_func, filetypes=[("All", "*")])
    assert out == "/picked/file.mp4"
    assert seen["parent"] is win
    assert ("attributes", ("-topmost", False)) in win.calls

    # failing window methods still run func (all guards are try/except)
    class _Bad:
        def deiconify(self):
            raise RuntimeError("x")

        def lift(self):
            raise RuntimeError("x")

        def attributes(self, *a):
            raise RuntimeError("x")

        def update_idletasks(self):
            raise RuntimeError("x")

    out2 = uw._file_dialog_top(_Bad(), fake_func)
    assert out2 == "/picked/file.mp4"


# ---- quality ----

def test_wav_peak_empty_and_helpers(tmp_path):
    from dubbing import quality as q
    empty = tmp_path / "empty.wav"
    with wave.open(str(empty), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"")
    assert q._wav_peak(empty) == 0.0
    assert q._wav_duration(_tiny_wav(tmp_path / "a.wav", seconds=0.5)) > 0.4
    assert q.repeated_ngram_ratio([]) == 0.0
    assert q.repeated_ngram_ratio(["hello world"]) == 0.0


def test_vocal_coverage_no_data(tmp_path):
    from dubbing import quality as q
    # srt but no timeline wav -> uncovered silent path
    (tmp_path / "dub.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nSzia\n", encoding="utf-8")
    assert q.vocal_coverage(tmp_path)["total"] == 1


def test_spell_unknown_rate_paths(monkeypatch):
    import dubbing.spellcheck as sc
    from dubbing import quality as q
    # no dictionary
    monkeypatch.setattr(sc, "available", lambda lang: False)
    r = q.spell_unknown_rate(["hello world foo"], lang="hu_HU")
    assert r["checked"] is False and "dictionary" in r["reason"]
    # backend error on available
    monkeypatch.setattr(sc, "available", lambda lang: (_ for _ in ()).throw(RuntimeError("boom")))
    r2 = q.spell_unknown_rate(["hello"], lang="hu_HU")
    assert r2["checked"] is False
    # empty words
    monkeypatch.setattr(sc, "available", lambda lang: True)
    r3 = q.spell_unknown_rate(["  . , "], lang="hu_HU")
    assert r3["checked"] is True and r3["total"] == 0
    # check raises
    monkeypatch.setattr(sc, "check", lambda lang, text: (_ for _ in ()).throw(RuntimeError("spell boom")))
    r4 = q.spell_unknown_rate(["hello world foo"], lang="hu_HU")
    assert r4["checked"] is False
    # ok path with fake hits
    monkeypatch.setattr(sc, "check", lambda lang, text: [("helo", ["hello"])])
    r5 = q.spell_unknown_rate(["helo world foo"], lang="hu_HU")
    assert r5["checked"] is True and r5["rate"] > 0


def test_mux_audit_numpy_missing(monkeypatch):
    import builtins

    from dubbing import quality as q
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("no numpy here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    res = q.mux_audit(Path("/tmp/a.mp4"), Path("/tmp/b.wav"))
    assert res["ok"] is False and "numpy" in res["reason"]


def test_mux_audit_too_short_and_error(monkeypatch, tmp_path):
    from dubbing import quality as q
    a = _tiny_wav(tmp_path / "a.wav", seconds=0.2)
    b = _tiny_wav(tmp_path / "b.wav", seconds=0.2)
    monkeypatch.setattr(q, "_extract_mono16k", lambda src, out: (out.write_bytes(b"x"), out)[1])
    monkeypatch.setattr(q, "_wav_samples", lambda p, max_seconds=3600.0: ([0.1] * 100, 16000))
    res = q.mux_audit(a, b)
    assert res["ok"] is False and res["reason"] == "too short to audit"
    # extraction error -> fails closed
    monkeypatch.setattr(q, "_extract_mono16k",
                        lambda src, out: (_ for _ in ()).throw(RuntimeError("ffmpeg gone")))
    res2 = q.mux_audit(a, b)
    assert res2["ok"] is False


def test_check_missing_and_parse_fail_and_empty(tmp_path, monkeypatch):
    from dubbing import quality as q
    # missing srt
    r = q.check(tmp_path)
    assert r["ok"] is False and "missing" in r["failures"][0]
    # parse failure
    (tmp_path / "dub.srt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(q, "parse_srt", lambda p: (_ for _ in ()).throw(RuntimeError("bad srt")))
    r2 = q.check(tmp_path)
    assert r2["ok"] is False and "parse failed" in r2["failures"][0]


def test_check_zero_segments_and_bad_transcript(tmp_path, monkeypatch):
    from dubbing import quality as q
    from dubbing.config import Segment
    (tmp_path / "dub.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
    monkeypatch.setattr(q, "parse_srt", lambda p: [])
    r = q.check(tmp_path)
    assert r["ok"] is False and "zero segments" in r["failures"]
    # bad transcript json is swallowed, gates still run
    monkeypatch.setattr(q, "parse_srt", lambda p: [Segment(0.0, 1.0, text="hello world foo bar",
                                                           translated="Szia")])
    (tmp_path / "dub_transcript.json").write_text("{not json", encoding="utf-8")
    _tiny_wav(tmp_path / "dub_timeline.wav", seconds=1.0)
    r2 = q.check(tmp_path)
    assert r2["segments"] == 1


def test_check_source_duration_branch(tmp_path, monkeypatch):
    import subprocess as _sp

    from dubbing import quality as q
    (tmp_path / "dub.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nSzia\n", encoding="utf-8")
    _tiny_wav(tmp_path / "dub_timeline.wav", seconds=2.0)
    monkeypatch.setattr(q, "vocal_coverage", lambda wd, floor=0.01: {"ratio": 1.0, "silent": [], "total": 1})
    monkeypatch.setattr("dubbing.ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(_sp, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="", stderr="  Duration: 00:00:02.00, start: 0\n"))
    r = q.check(tmp_path, source_media=tmp_path / "src.mp4")
    assert r.get("source_dur_s") == 2.0
    assert r["ok"] is True
    # out-of-range duration fails the gate
    monkeypatch.setattr(_sp, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="", stderr="  Duration: 00:01:00.00, start: 0\n"))
    r2 = q.check(tmp_path, source_media=tmp_path / "src.mp4")
    assert r2["ok"] is False and any("±25%" in f or "25%" in f for f in r2["failures"])
    # probe error swallowed
    monkeypatch.setattr(_sp, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no ff")))
    r3 = q.check(tmp_path, source_media=tmp_path / "src.mp4")
    assert "source_dur_s" not in r3


def test_quality_main(tmp_path, capsys):
    from dubbing.quality import main
    (tmp_path / "dub.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nSzia\n", encoding="utf-8")
    rc = main(["--work", str(tmp_path)])
    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert "segments" in out


# ---- dubbing package ----

def test_lang_label_code_edges():
    import dubbing as d
    assert d.dub_language_label("") == " ()"
    assert d.dub_language_label("xx") == "XX (xx)"
    assert d.dub_language_code("") == "en"
    assert d.dub_language_code("Hungarian (hu)") == "hu"
    assert d.dub_language_code("hu") == "hu"
    assert d.dub_language_code("pt_PT-tugão") == "pt"
    assert d.is_cyhunspell_build_failure("autoreconf failed for cyhunspell") is True
    assert d.is_cyhunspell_build_failure("all good") is False
    assert d._escape_sub_path("a:b'c\\d") == "'a\\:b\\'c\\\\d'"


def test_run_and_has_libass_paths(monkeypatch):
    import subprocess as _sp

    import dubbing as d
    monkeypatch.setattr(_sp, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no proc")))
    assert d._run("ffmpeg", "-x") == (1, "no proc")
    d._libass_cache = None
    monkeypatch.setattr(d, "_run", lambda *a, **k: (1, ""))
    assert d.has_libass() is False
    d._libass_cache = True
    assert d.has_libass() is True
    d._libass_cache = None


def test_has_backends_and_missing_deps(monkeypatch):
    import dubbing as d
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert d.has_faster_whisper() is False
    monkeypatch.setitem(sys.modules, "transformers", None)
    assert d.has_nllb() is False
    monkeypatch.setitem(sys.modules, "TTS", types.SimpleNamespace())
    assert d.has_xtts() is True
    monkeypatch.setitem(sys.modules, "TTS", None)
    assert d.has_xtts() is False
    items = d.missing_dependencies(separation_enabled=True, engine="XTTS v2")
    keys = {i["key"] for i in items}
    assert {"faster-whisper", "separator", "xtts", "libass"} <= keys
    items2 = d.missing_dependencies(separation_enabled=False, engine="Piper")
    keys2 = {i["key"] for i in items2}
    assert "separator" not in keys2 and "xtts" not in keys2
    specs = d.pip_missing_specs(separation_enabled=False, engine="XTTS v2")
    assert isinstance(specs, list) and len(specs) == len(set(specs))
