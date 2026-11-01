from __future__ import annotations

import json

import pytest

from app import DEFAULT_AUDIO_SETTINGS
from app import DEFAULT_DOCUMENT_CONVERSION_SETTINGS
from app import DEFAULT_GENERAL_SETTINGS
from app import DEFAULT_LANG_LEARNING_SETTINGS
from app import DEFAULT_PATHS_SETTINGS
from app import DEFAULT_PIPER_VOICE_BY_LANGUAGE
from app import DEFAULT_UI_SETTINGS
from app import default_piper_voice_for_language
from app import load_app_settings
from app import normalize_app_settings
from app import normalize_general_language
from app import normalize_learning_language
from app import normalize_piper_voice_defaults
from app import save_app_settings
from app import system_language_code

DEFAULT_SECTIONS = {
    "language_learning": DEFAULT_LANG_LEARNING_SETTINGS,
    "ui": DEFAULT_UI_SETTINGS,
    "audio": DEFAULT_AUDIO_SETTINGS,
    "general": DEFAULT_GENERAL_SETTINGS,
    "paths": DEFAULT_PATHS_SETTINGS,
    "document_conversion": DEFAULT_DOCUMENT_CONVERSION_SETTINGS,
    "default_piper_voice_by_language": DEFAULT_PIPER_VOICE_BY_LANGUAGE,
}
DEFAULT_SECTIONS["general"] = {
    **DEFAULT_GENERAL_SETTINGS,
    "default_language": system_language_code(),
}


class TestLoadAppSettings:
    def test_file_exists_with_valid_json(self, temp_dir):
        path = temp_dir / "settings.json"
        path.write_text(json.dumps({"default_piper_voice_label": "test"}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        expected = {"default_piper_voice_label": "test", **DEFAULT_SECTIONS}
        assert result == expected

    def test_file_does_not_exist_returns_empty_dict(self, temp_dir):
        path = temp_dir / "nonexistent.json"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        assert result == DEFAULT_SECTIONS

    def test_file_does_not_exist_uses_supported_system_locale(self, temp_dir, monkeypatch):
        path = temp_dir / "nonexistent.json"
        monkeypatch.setattr("app.APP_SETTINGS_PATH", path)
        monkeypatch.setattr("app.locale.getlocale", lambda: ("fr_FR", "UTF-8"))
        assert load_app_settings()["general"]["default_language"] == "fr"

    def test_missing_preference_uses_english_for_unsupported_locale(self, monkeypatch):
        monkeypatch.setattr("app.locale.getlocale", lambda: ("eo_EO", "UTF-8"))
        settings = normalize_app_settings({"general": {"default_engine": "Auto"}})
        assert settings["general"]["default_language"] == "en"

    def test_saved_language_preference_takes_precedence_over_locale(self, monkeypatch):
        monkeypatch.setattr("app.locale.getlocale", lambda: ("fr_FR", "UTF-8"))
        settings = normalize_app_settings({"general": {"default_language": "es"}})
        assert settings["general"]["default_language"] == "es"

    def test_file_has_invalid_json_returns_defaults(self, temp_dir):
        path = temp_dir / "settings.json"
        path.write_text("not valid json{{{")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        # Returns defaults even on invalid JSON
        assert result == DEFAULT_SECTIONS


class TestSaveAppSettings:
    def test_writes_valid_json(self, temp_dir):
        path = temp_dir / "settings.json"
        data = {"key": "value", "number": 42}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            save_app_settings(data)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_round_trip_preserves_data(self, temp_dir):
        path = temp_dir / "settings.json"
        data = {"default_piper_voice_label": "English US | Lessac | medium"}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            save_app_settings(data)
            loaded = load_app_settings()
        expected = {**data, **DEFAULT_SECTIONS}
        assert loaded == expected


class TestSettingsMigration:
    def test_legacy_system_theme_migrates_to_light(self):
        settings = normalize_app_settings({"ui": {"theme": "system"}})
        assert settings["ui"]["theme"] == "light"

    def test_explicit_theme_is_preserved(self):
        settings = normalize_app_settings({"ui": {"theme": "dark"}})
        assert settings["ui"]["theme"] == "dark"

    def test_language_learning_display_name_migrates_to_code(self):
        settings = normalize_app_settings({"language_learning": {"language": "Spanish"}})
        assert settings["language_learning"]["language"] == "es"

    def test_unknown_language_learning_value_falls_back_to_portuguese(self):
        assert normalize_learning_language("Hungarian") == "pt"
        assert normalize_learning_language(None) == "pt"

    def test_general_language_display_name_migrates_to_code(self):
        settings = normalize_app_settings({"general": {"default_language": "English"}})
        assert settings["general"]["default_language"] == "en"

    def test_unknown_general_language_falls_back_to_default(self):
        assert normalize_general_language("Klingon") == "en"

    def test_piper_voice_defaults_normalize_supported_language_keys_and_labels(self):
        assert normalize_piper_voice_defaults(
            {"EN_us": "English voice", "bad code !": "ignored", "hu": "  "}
        ) == {"en-us": "English voice"}

    def test_per_language_piper_default_precedes_legacy_global_default(self):
        options = {
            "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium"},
            "English US | Lessac | medium": {"code": "en_US-lessac-medium"},
        }
        settings = {
            "default_piper_voice_label": "Hungarian | Anna | medium",
            "default_piper_voice_by_language": {
                "en": "English US | Lessac | medium",
            },
        }
        assert default_piper_voice_for_language(settings, "en", options) == "English US | Lessac | medium"
        assert default_piper_voice_for_language(settings, "hu", options) == "Hungarian | Anna | medium"

    def test_invalid_per_language_piper_default_falls_back_to_first_language_voice(self):
        options = {
            "English US | Lessac | medium": {"code": "en_US-lessac-medium"},
            "English GB | Alan | medium": {"code": "en_GB-alan-medium"},
        }
        settings = {"default_piper_voice_by_language": {"en": "removed voice"}}
        assert default_piper_voice_for_language(settings, "en", options) == "English US | Lessac | medium"

    def test_target_sentence_repetition_defaults_to_disabled(self):
        settings = normalize_app_settings({"language_learning": {}})
        assert settings["language_learning"]["repeat_target_sentence"] is False

    def test_mp3_quality_defaults_to_64_kbps(self):
        settings = normalize_app_settings({"audio": {}})
        assert settings["audio"]["mp3_quality"] == "64 kbps"
