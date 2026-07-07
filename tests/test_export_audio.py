from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import export_audio_segment, output_format_for_path


class TestExportAudioSegment:
    def test_default_mp3_uses_192k(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        mock_audio.export.assert_called_once()
        call_kwargs = mock_audio.export.call_args[1]
        assert call_kwargs["format"] == "mp3"
        assert call_kwargs["bitrate"] == "192k"
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

    def test_sample_rate_always_44100(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output, bitrate="128k")

        call_kwargs = mock_audio.export.call_args[1]
        params = call_kwargs["parameters"]
        assert "-ar" in params
        assert "44100" in params

    def test_backward_compat_no_new_params(self, tmp_path):
        mock_audio = MagicMock()
        output = tmp_path / "test.mp3"

        with patch("app.imageio_ffmpeg.get_ffmpeg_exe", return_value="/fake/ffmpeg"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                export_audio_segment(mock_audio, output)

        mock_audio.export.assert_called_once()
        assert mock_audio.export.call_args[1]["bitrate"] == "192k"


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
