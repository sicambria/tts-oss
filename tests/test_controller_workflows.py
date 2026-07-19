from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import app
from app import App
from app import SettingsDialog


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Text:
    def __init__(self, value=""):
        self.value = value
        self.tags = []

    def get(self, *_):
        return self.value

    def delete(self, *_):
        self.value = ""

    def insert(self, *_args):
        self.value = _args[-1]

    def tag_remove(self, *_):
        pass

    def tag_add(self, *args):
        self.tags.append(args)

    def see(self, *_):
        pass

    def index(self, value):
        return value if value != "insert" else "1.3"

    def count(self, *_):
        return [len(self.value)]

    def tag_ranges(self, *_):
        return ()


def controller():
    value = App.__new__(App)
    value.root = MagicMock()
    value.text = Text("Hello world")
    value.log = Text("log line")
    value.status = Var("Ready")
    value.sidebar_collapsed = Var(False)
    value.sidebar_frame = MagicMock()
    value.sidebar_toggle = MagicMock()
    value.practice_session = None
    value.read_translations = Var(False)
    value.language_display = Var("Hungarian")
    value.read_translations_check = MagicMock()
    value.export_pairs_button = MagicMock()
    value.clear_read_aloud_highlight = MagicMock()
    value.enqueue_log = MagicMock()
    value.settings = {"general": {"confirm_on_exit": True}}
    value.player = MagicMock()
    value.playback_toggle_label = Var("Pause")
    value.playback_toggle_button = MagicMock()
    value.worker = None
    value.voice_wizard = value.doc_wizard = value.lang_learning_wizard = None
    return value


@pytest.mark.unit
def test_window_geometry_and_message_wrappers():
    window = MagicMock()
    window.winfo_screenwidth.return_value = 1000
    window.winfo_screenheight.return_value = 700
    app.set_initial_window_geometry(window, width_fraction=0.9, height_fraction=0.9, min_width=900, min_height=650)
    window.geometry.assert_called_once_with("900x636+50+32")
    with patch("app.messagebox.showinfo", return_value="ok") as info:
        assert app.show_info(window, "Title", "Message") == "ok"
    info.assert_called_once_with("Title", "Message", parent=window)


@pytest.mark.unit
def test_theme_and_audio_export_options():
    style = MagicMock()
    with patch("app.ttk.Style", return_value=style):
        app.apply_theme("dark")
    assert app.CURRENT_THEME == "dark" and app.ACCENT == app.THEMES["dark"]["accent"]
    assert app.mp3_sample_rate_for_bitrate("8k") == 8000
    assert app.mp3_sample_rate_for_bitrate("bad") == 44100
    assert app.audio_export_options({"audio": {"mp3_quality": "128 kbps"}}, Path("a.mp3"))["bitrate"] == "128k"
    assert "quality_params" in app.audio_export_options({}, Path("a.ogg"))


@pytest.mark.integration
def test_app_language_pair_and_playback_controller_actions(tmp_path):
    value = controller()
    with patch("app.save_app_settings"):
        value.activate_language_practice([("Olá", "Hello")], "pt", 500, speak=False)
    assert value.text.value == "Olá\nHello" and value.read_translations.get()
    assert value.current_language_pairs() == [("Olá", "Hello")]
    value._collapse_sidebar()
    assert value.sidebar_collapsed.get()
    value._expand_sidebar()
    assert not value.sidebar_collapsed.get()
    value.player.is_active.return_value = True
    value.player.is_paused.return_value = False
    value.toggle_playback_pause()
    value.player.pause.assert_called_once()
    value.player.is_paused.return_value = True
    value.toggle_playback_pause()
    value.player.resume.assert_called_once()
    value.new_document()
    assert value.text.value == "" and value.practice_session is None
    value.log.value = "audit"
    target = tmp_path / "audit.txt"
    with patch("app.filedialog.asksaveasfilename", return_value=str(target)):
        value.export_log()
    assert target.read_text(encoding="utf-8") == "audit"


@pytest.mark.unit
def test_settings_dialog_collect_apply_and_reset():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.window = MagicMock()
    dialog.app = MagicMock()
    dialog.app.settings = {}
    dialog.app.root = MagicMock()
    dialog.app.voice_wizard = dialog.app.doc_wizard = dialog.app.lang_learning_wizard = None
    for name, value in {
        "general_engine_var": "Piper",
        "general_lang_var": "Portuguese",
        "general_output_var": "/tmp/out",
        "general_autosave_var": True,
        "general_confirm_exit_var": False,
        "advanced_xtts_var": True,
        "audio_format_var": "MP3",
        "audio_mp3_var": "64 kbps",
        "audio_ogg_var": "High (q5)",
        "audio_sr_var": 44100,
        "audio_device_var": "",
        "appearance_theme_var": "dark",
        "appearance_font_var": 12,
        "appearance_compact_var": True,
        "appearance_sidebar_var": False,
        "advanced_piper_dir_var": "piper",
        "advanced_pocket_dir_var": "pocket",
        "advanced_log_var": "DEBUG",
    }.items():
        setattr(dialog, name, Var(value))
    settings = dialog._collect_settings()
    assert settings["general"]["default_language"] == "pt"
    with (
        patch("app.save_app_settings") as save,
        patch("app.resolve_theme", return_value="dark"),
        patch("app.apply_theme"),
    ):
        dialog._apply_settings(settings)
    save.assert_called_once()
    dialog.app._rebuild_styles.assert_called_once()
    with (
        patch("app.ask_yes_no", return_value=True),
        patch("app.save_app_settings"),
        patch("app.SettingsDialog") as reopened,
    ):
        dialog._on_reset()
    reopened.assert_called_once_with(dialog.app)
