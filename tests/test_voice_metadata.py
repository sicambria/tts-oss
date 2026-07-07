from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app import DEFAULT_PIPER_VOICE_LABEL
from app import PIPER_VOICE_OPTIONS
from app import discover_local_piper_voices
from app import get_piper_voice_metadata
from app import label_for_piper_voice
from app import piper_model_path


class TestGetPiperVoiceMetadata:
    def test_known_label_returns_correct_dict(self):
        result = get_piper_voice_metadata("Hungarian | Anna | medium")
        assert result["code"] == "hu_HU-anna-medium"

    def test_unknown_label_falls_back_to_default(self):
        result = get_piper_voice_metadata("nonexistent label")
        default = PIPER_VOICE_OPTIONS[DEFAULT_PIPER_VOICE_LABEL]
        assert result == default

    def test_default_label_returns_itself(self):
        result = get_piper_voice_metadata(DEFAULT_PIPER_VOICE_LABEL)
        assert result["code"] == PIPER_VOICE_OPTIONS[DEFAULT_PIPER_VOICE_LABEL]["code"]


class TestLabelForPiperVoice:
    def test_with_full_voice_info(self):
        info = {
            "language": {"name_english": "Hungarian", "country_english": "Hungary"},
            "name": "anna",
            "quality": "medium",
        }
        label = label_for_piper_voice("hu_HU-anna-medium", info)
        assert "Hungarian" in label
        assert "Hungary" in label
        assert "Anna" in label
        assert "medium" in label

    def test_without_voice_info_parses_by_convention(self):
        label = label_for_piper_voice("hu_HU-anna-medium")
        assert "Hungarian" in label
        assert "Anna" in label
        assert "medium" in label

    def test_two_part_code(self):
        label = label_for_piper_voice("en_US-lessac")
        assert "English United States" in label
        assert "Lessac" in label

    def test_known_language_codes_mapped(self):
        label = label_for_piper_voice("en_GB-alan-medium")
        assert "English Great Britain" in label

    def test_unknown_language_code_used_as_is(self):
        label = label_for_piper_voice("zz_ZZ-voice-medium")
        assert "zz_ZZ" in label


class TestDiscoverLocalPiperVoices:
    def test_empty_dir_returns_builtins(self, temp_dir):
        with patch("app.PIPER_VOICE_DIR", temp_dir):
            result = discover_local_piper_voices()
        for builtin_label in PIPER_VOICE_OPTIONS:
            assert builtin_label in result

    def test_new_onnx_adds_to_options(self, temp_dir):
        (temp_dir / "fr_FR-test-medium.onnx").write_text("fake model")
        (temp_dir / "fr_FR-test-medium.onnx.json").write_text("{}")
        with patch("app.PIPER_VOICE_DIR", temp_dir):
            result = discover_local_piper_voices()
        assert any(meta["code"] == "fr_FR-test-medium" for meta in result.values())

    def test_onnx_without_json_is_skipped(self, temp_dir):
        (temp_dir / "nojson-voice-medium.onnx").write_text("fake model")
        with patch("app.PIPER_VOICE_DIR", temp_dir):
            result = discover_local_piper_voices()
        assert not any(meta["code"] == "nojson-voice-medium" for meta in result.values())

    def test_already_known_voice_not_duplicated(self, temp_dir):
        (temp_dir / "hu_HU-anna-medium.onnx").write_text("fake")
        (temp_dir / "hu_HU-anna-medium.onnx.json").write_text("{}")
        with patch("app.PIPER_VOICE_DIR", temp_dir):
            result = discover_local_piper_voices()
        codes = [meta["code"] for meta in result.values()]
        assert codes.count("hu_HU-anna-medium") == 1


class TestPiperModelPath:
    def test_constructs_correct_path(self):
        result = piper_model_path("test-voice")
        assert result.name == "test-voice.onnx"

    def test_returns_path_object(self):
        result = piper_model_path("test-voice")
        assert isinstance(result, Path)
