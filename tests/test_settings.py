from __future__ import annotations

import json

import pytest

from app import DEFAULT_LANG_LEARNING_SETTINGS
from app import load_app_settings
from app import save_app_settings


class TestLoadAppSettings:
    def test_file_exists_with_valid_json(self, temp_dir):
        path = temp_dir / "settings.json"
        path.write_text(json.dumps({"default_piper_voice_label": "test"}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        expected = {"default_piper_voice_label": "test", "language_learning": DEFAULT_LANG_LEARNING_SETTINGS}
        assert result == expected

    def test_file_does_not_exist_returns_empty_dict(self, temp_dir):
        path = temp_dir / "nonexistent.json"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        assert result == {}

    def test_file_has_invalid_json_returns_empty_dict(self, temp_dir):
        path = temp_dir / "settings.json"
        path.write_text("not valid json{{{")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.APP_SETTINGS_PATH", path)
            result = load_app_settings()
        # Returns defaults even on invalid JSON
        expected = {"language_learning": DEFAULT_LANG_LEARNING_SETTINGS}
        assert result == expected


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
        expected = {**data, "language_learning": DEFAULT_LANG_LEARNING_SETTINGS}
        assert loaded == expected
