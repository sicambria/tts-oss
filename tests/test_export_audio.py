from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import audio_export_options
from app import export_audio_segment
from app import output_format_for_path


class TestExportAudioSegment:
    def test_default_mp3_uses_64k(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        mock_audio.export.assert_called_once()
        call_kwargs = mock_audio.export.call_args[1]
        assert call_kwargs["format"] == "mp3"
        assert call_kwargs["bitrate"] == "64k"
        assert "-ar" in call_kwargs.get("parameters", [])
        assert "44100" in call_kwargs.get("parameters", [])

    def test_custom_bitrate_mp3(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output, bitrate="320k")

        call_kwargs = mock_audio.export.call_args[1]
        assert call_kwargs["bitrate"] == "320k"

    def test_custom_quality_ogg(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.ogg"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output, quality_params=["-q:a", "5"])

        call_kwargs = mock_audio.export.call_args[1]
        assert call_kwargs["format"] == "ogg"
        params = call_kwargs["parameters"]
        assert "-ar" in params
        assert "44100" in params
        assert "-q:a" in params
        assert "5" in params
        assert "bitrate" not in call_kwargs

    def test_quality_params_wins_over_bitrate(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.ogg"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(
                    mock_audio,
                    output,
                    bitrate="192k",
                    quality_params=["-q:a", "8"],
                )

        call_kwargs = mock_audio.export.call_args[1]
        assert "bitrate" not in call_kwargs
        assert "-q:a" in call_kwargs["parameters"]

    def test_wav_no_bitrate(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.wav"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        call_kwargs = mock_audio.export.call_args[1]
        assert call_kwargs["format"] == "wav"
        assert "bitrate" not in call_kwargs

    def test_creates_output_directory(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "nested" / "dir" / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        assert output.parent.exists()

    def test_standard_mp3_bitrate_uses_44100_hz(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output, bitrate="128k")

        call_kwargs = mock_audio.export.call_args[1]
        params = call_kwargs["parameters"]
        assert "-ar" in params
        assert "44100" in params

    @pytest.mark.parametrize(
        ("bitrate", "sample_rate"),
        [("8k", "8000"), ("16k", "12000"), ("24k", "12000"), ("32k", "16000")],
    )
    def test_low_mp3_bitrates_use_supported_sample_rates(self, tmp_path, bitrate, sample_rate):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output, bitrate=bitrate)

        assert sample_rate in mock_audio.export.call_args[1]["parameters"]

    def test_backward_compat_no_new_params(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        mock_audio.export.assert_called_once()
        assert mock_audio.export.call_args[1]["bitrate"] == "64k"


class TestAudioExportOptions:
    def test_uses_the_saved_low_mp3_preset(self):
        options = audio_export_options({"audio": {"mp3_quality": "16 kbps"}}, Path("speech.mp3"))

        assert options == {"bitrate": "16k"}

    def test_uses_64_kbps_when_the_mp3_preset_is_missing(self):
        options = audio_export_options({}, Path("speech.mp3"))

        assert options == {"bitrate": "64k"}


class TestOutputFormatForPath:
    def test_mp3(self):
        assert output_format_for_path(Path("file.mp3")) == "mp3"

    def test_ogg(self):
        assert output_format_for_path(Path("file.ogg")) == "ogg"

    def test_wav(self):
        assert output_format_for_path(Path("file.wav")) == "wav"

    def test_uppercase(self):
        assert output_format_for_path(Path("file.MP3")) == "mp3"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported output format"):
            output_format_for_path(Path("file.flac"))
