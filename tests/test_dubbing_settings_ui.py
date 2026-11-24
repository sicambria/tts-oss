"""Settings UI upgrade: subtitle style, formats, refresh RCA, persistence."""
from __future__ import annotations

from pathlib import Path


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Btn:
    def __init__(self):
        self.states = []

    def state(self, s):
        self.states.append(list(s))


def _wizard(**over):
    from dubbing import ui_wizard as uw
    wiz = uw.DubbingWizard.__new__(uw.DubbingWizard)
    wiz.input_path = _Var(over.get("input", ""))
    wiz.engine = _Var(over.get("engine", "XTTS v2"))
    wiz.burn_in = _Var(over.get("burn", True))
    wiz.burn_note = _Var("")
    wiz.voice_note = _Var("")
    wiz.burn_btn = _Btn()
    wiz.app = over.get("app", None)
    return wiz


def test_reset_libass_cache():
    import dubbing as d
    d._libass_cache = False
    d.reset_libass_cache()
    assert d._libass_cache is None
    d._libass_cache = True
    d.reset_libass_cache()
    assert d._libass_cache is None


def test_refresh_enables_for_video_with_libass(monkeypatch):
    from dubbing import ui_wizard as uw
    monkeypatch.setattr(uw, "has_libass", lambda: True)
    wiz = _wizard(input="song.mp4", burn=True)
    wiz._refresh()
    assert ["!disabled"] in wiz.burn_btn.states
    assert wiz.burn_in.get() is True
    assert wiz.burn_note.get() == ""


def test_refresh_preserves_intent_without_input(monkeypatch):
    from dubbing import ui_wizard as uw
    monkeypatch.setattr(uw, "has_libass", lambda: True)
    wiz = _wizard(input="", burn=True)
    wiz._refresh()
    assert ["disabled"] in wiz.burn_btn.states
    assert wiz.burn_in.get() is True  # intent kept, not wiped
    assert "video" in wiz.burn_note.get()


def test_refresh_forces_off_for_audio(monkeypatch):
    from dubbing import ui_wizard as uw
    monkeypatch.setattr(uw, "has_libass", lambda: True)
    wiz = _wizard(input="song.mp3", burn=True)
    wiz._refresh()
    assert ["disabled"] in wiz.burn_btn.states
    assert wiz.burn_in.get() is False
    assert "audio" in wiz.burn_note.get().lower()


def test_refresh_disabled_when_libass_missing(monkeypatch):
    from dubbing import ui_wizard as uw
    monkeypatch.setattr(uw, "has_libass", lambda: False)
    wiz = _wizard(input="clip.mp4", burn=True)
    wiz._refresh()
    assert ["disabled"] in wiz.burn_btn.states
    assert wiz.burn_in.get() is True  # video intent kept; needs libass
    assert "libass" in wiz.burn_note.get()


def test_refresh_typed_path_same_as_browsed(monkeypatch):
    """RCA: manual Entry edits previously never re-evaluated (no trace)."""
    from dubbing import ui_wizard as uw
    monkeypatch.setattr(uw, "has_libass", lambda: True)
    wiz = _wizard(input="", burn=False)
    wiz._refresh()
    assert ["disabled"] in wiz.burn_btn.states
    wiz.input_path.set("typed.MKV")  # what the trace_add handler re-runs for
    wiz._refresh()
    assert ["!disabled"] in wiz.burn_btn.states


def test_dub_defaults_full_roundtrip():
    from dubbing import ui_wizard as uw
    fresh = uw.dub_defaults({})
    assert fresh["whisper_model"] == "small"
    assert fresh["audio_output_format"] == "mp3"
    assert fresh["video_output_format"] == "mp4"
    assert fresh["subtitle_track"] == "translated"
    assert fresh["subtitle_font_size"] == 20
    assert fresh["subtitle_font_color"] == "&H00FFFFFF"
    assert fresh["subtitle_outline"] == 2
    assert fresh["output_folder"] == ""
    stored = uw.dub_defaults({
        "whisper_model": "medium", "audio_output_format": "wav",
        "video_output_format": "mkv", "subtitle_track": "source",
        "subtitle_font_size": 24, "subtitle_font_color": "&H000000FF",
        "subtitle_outline": 1, "output_folder": "/tmp/dubs",
    })
    assert stored["whisper_model"] == "medium"
    assert stored["audio_output_format"] == "wav"
    assert stored["video_output_format"] == "mkv"
    assert stored["subtitle_track"] == "source"
    assert stored["subtitle_font_size"] == 24
    assert stored["subtitle_outline"] == 1
    assert stored["output_folder"] == "/tmp/dubs"
    # invalid stored choices fall back to defaults, never crash
    bad = uw.dub_defaults({"whisper_model": "xxl", "audio_output_format": "flac",
                           "video_output_format": "avi", "subtitle_track": "both"})
    assert bad["whisper_model"] == "small"
    assert bad["audio_output_format"] == "mp3"
    assert bad["video_output_format"] == "mp4"
    assert bad["subtitle_track"] == "translated"


def test_build_subtitle_style():
    from dubbing.subtitles import build_subtitle_style
    assert build_subtitle_style() == "FontSize=20,PrimaryColour=&H00FFFFFF,Outline=2"
    assert build_subtitle_style(24, "&H000000FF", 1) == "FontSize=24,PrimaryColour=&H000000FF,Outline=1"
    for bad in (11, 33, "big"):
        try:
            build_subtitle_style(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"size {bad!r} should raise")
    for bad in ("red", "&HZZZZZZZZ", "&H123"):
        try:
            build_subtitle_style(20, bad, 2)
        except ValueError:
            pass
        else:
            raise AssertionError(f"color {bad!r} should raise")
    for bad in (-1, 5, "x"):
        try:
            build_subtitle_style(20, "&H00FFFFFF", bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"outline {bad!r} should raise")


def test_build_burn_filter_adversarial_path():
    from dubbing.subtitles import build_burn_filter
    nasty = Path("/tmp/my: show's day/ep 1.srt")
    args = build_burn_filter(nasty, "FontSize=20,PrimaryColour=&H00FFFFFF,Outline=2")
    assert len(args) == 2 and args[0] == "-vf"
    assert "force_style='FontSize=20,PrimaryColour=&H00FFFFFF,Outline=2'" in args[1]
    plain = build_burn_filter(nasty)
    assert len(plain) == 2 and "force_style" not in plain[1]


def test_validate_new_keys(tmp_path):
    from dubbing.config import DubJob
    good = DubJob(input=tmp_path / "a.mp4", subtitle_track="source",
                  subtitle_font_size=24, subtitle_font_color="&H000000FF",
                  subtitle_outline=1)
    good.validate()
    import pytest
    for kw in ({"subtitle_track": "both"}, {"subtitle_font_size": 99},
               {"subtitle_font_color": "red"}, {"subtitle_outline": 9}):
        with pytest.raises(ValueError):
            DubJob(input=tmp_path / "a.mp4", **kw).validate()


def test_mux_video_passes_style(monkeypatch, tmp_path):
    import dubbing.video as vmod
    monkeypatch.setattr(vmod, "has_libass", lambda: True)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return types_ns(0)

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)
    out = tmp_path / "dub.mp4"
    res = vmod.mux_video(tmp_path / "in.mp4", tmp_path / "mix.wav",
                         tmp_path / "dub.srt", out, True, style="FontSize=24")
    assert res == out
    vf = seen["cmd"][seen["cmd"].index("-vf") + 1]
    assert "force_style='FontSize=24'" in vf


def types_ns(code):
    import types
    return types.SimpleNamespace(returncode=code, stdout="", stderr="")


def test_pipeline_source_track_uses_source_srt(monkeypatch, tmp_path):
    import dubbing.video as vmod
    from dubbing import stages as stages_mod
    from dubbing.config import DubJob
    from dubbing.config import Segment
    from dubbing.pipeline import DubPipeline
    seen = {}

    def fake_mux(video, wav, srt, out, burn, style=None):
        seen["srt"] = Path(srt).name
        seen["style"] = style
        out.write_bytes(b"v")
        return out

    monkeypatch.setattr(vmod, "mux_video", fake_mux)
    monkeypatch.setattr(stages_mod, "fit_to_slot", lambda wav, dur, wd=None: (wav, False))
    monkeypatch.setattr(stages_mod, "concat_timeline",
                        lambda placed, total, out: (out.write_bytes(b"mix"), out)[1])
    monkeypatch.setattr(stages_mod, "mix_with_bg",
                        lambda dub, bg, ratio, out, **kw: (out.write_bytes(b"mix"), out)[1])
    job = DubJob(input=tmp_path / "a.mp4", target_lang="hu", output_dir=tmp_path / "out",
                 subtitle_track="source")
    pipe = DubPipeline(job, log=lambda m: None)
    out = pipe.run(tmp_path,
                   extract=lambda s, d: (d.write_bytes(b"x"), d)[1],
                   transcribe=lambda v: [Segment(0.0, 1.0, text="hello")],
                   translate=lambda segs, s, t: segs,
                   synthesize=lambda text, hint: (hint.write_bytes(b"w"), hint)[1],
                   full=True)
    assert out.suffix == ".mp4"
    assert seen["srt"] == "dub_source.srt"
    assert seen["style"] == "FontSize=20,PrimaryColour=&H00FFFFFF,Outline=2"


def test_on_close_persists_all_keys(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "save_app_settings", lambda settings: None)
    from dubbing import ui_wizard as uw
    wiz = uw.DubbingWizard.__new__(uw.DubbingWizard)
    wiz.source_lang = _Var("Hungarian (hu)")
    wiz.target_lang = _Var("English (en)")
    wiz.engine = _Var("Piper")
    wiz.separation = _Var(True)
    wiz.burn_in = _Var(True)
    wiz.bg_speech = _Var(30.0)
    wiz.bg_gap = _Var(80.0)
    wiz.bg_duck = _Var(False)
    wiz.whisper_model = _Var("medium")
    wiz.audio_format = _Var("wav")
    wiz.video_format = _Var("mkv")
    wiz.subtitle_track = _Var("source")
    wiz.subtitle_font_size = _Var("24")
    wiz.subtitle_font_color = _Var("&H000000FF")
    wiz.subtitle_outline = _Var("1")
    wiz.output_folder = _Var("/tmp/dubs")

    class _Win:
        def destroy(self):
            pass

    wiz.window = _Win()
    wiz.app = type("A", (), {"settings": {"dubbing": {}}, "dub_wizard": None})()
    wiz._on_close()
    saved = wiz.app.settings["dubbing"]
    assert saved["burn_in"] is True
    assert saved["whisper_model"] == "medium"
    assert saved["audio_output_format"] == "wav"
    assert saved["video_output_format"] == "mkv"
    assert saved["subtitle_track"] == "source"
    assert saved["subtitle_font_size"] == "24"
    assert saved["subtitle_font_color"] == "&H000000FF"
    assert saved["subtitle_outline"] == "1"
    assert saved["output_folder"] == "/tmp/dubs"
    assert saved["engine"] == "Piper"
    assert saved["keep_bg_ratio"] == 0.3
