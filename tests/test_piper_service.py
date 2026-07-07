from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import PiperService
from app import SynthesisRequest


def _make_request(text: str = "Hello world.", **overrides) -> SynthesisRequest:
    defaults = {
        "text": text,
        "language": "en",
        "output_file": Path("/tmp/out.mp3"),
        "engine": "Piper",
        "piper_voice_label": "English US | Lessac | medium",
        "piper_voice_code": "en_US-lessac-medium",
        "speaker_name": "Ana Florence",
        "speaker_wav": "",
    }
    defaults.update(overrides)
    return SynthesisRequest(**defaults)


@pytest.mark.unit
class TestPiperServiceEnsureLoaded:
    def test_missing_onnx_raises(self):
        svc = PiperService(log=MagicMock())
        with patch("app.piper_model_path", return_value=Path("/nonexistent/voice.onnx")):
            with pytest.raises(RuntimeError, match="is missing"):
                svc.ensure_loaded("nonexistent")

    def test_missing_piper_import_raises(self):
        svc = PiperService(log=MagicMock())
        model_path = Path("/fake/voice.onnx")
        with patch("app.piper_model_path", return_value=model_path):
            with patch.object(Path, "exists", return_value=True):
                with patch.dict("sys.modules", {"piper": None, "piper.voice": None}):
                    with pytest.raises(RuntimeError, match="Piper is not installed"):
                        svc.ensure_loaded("test-code")


@pytest.mark.unit
class TestPiperServiceIterSegments:
    def test_empty_text_raises(self):
        svc = PiperService(log=MagicMock())
        with patch.object(svc, "ensure_loaded", return_value=MagicMock()):
            with pytest.raises(ValueError, match="empty"):
                list(svc.iter_segments(_make_request(text="")))

    def test_single_chunk(self):
        svc = PiperService(log=MagicMock())
        mock_voice = MagicMock()
        mock_audio = MagicMock()
        mock_audio.audio_int16_bytes = b"\x00\x00"
        mock_audio.sample_width = 2
        mock_audio.sample_rate = 22050
        mock_audio.sample_channels = 1
        mock_voice.synthesize.return_value = [mock_audio]

        with patch.object(svc, "ensure_loaded", return_value=mock_voice):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                results = list(svc.iter_segments(_make_request(text="Hello.")))
        assert len(results) == 1
        chunk, segment = results[0]
        assert chunk.text.strip()

    def test_multi_chunk(self):
        svc = PiperService(log=MagicMock())
        mock_voice = MagicMock()
        mock_audio = MagicMock()
        mock_audio.audio_int16_bytes = b"\x00\x00"
        mock_audio.sample_width = 2
        mock_audio.sample_rate = 22050
        mock_audio.sample_channels = 1
        mock_voice.synthesize.return_value = [mock_audio]

        long_text = " ".join(["word"] * 200)

        with patch.object(svc, "ensure_loaded", return_value=mock_voice):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                results = list(svc.iter_segments(_make_request(text=long_text)))
        assert len(results) > 1


@pytest.mark.unit
class TestPiperServiceSynthesize:
    def test_combines_segments_with_pause(self):
        svc = PiperService(log=MagicMock())
        mock_voice = MagicMock()
        mock_audio = MagicMock()
        mock_audio.audio_int16_bytes = b"\x00\x00" * 100
        mock_audio.sample_width = 2
        mock_audio.sample_rate = 22050
        mock_audio.sample_channels = 1
        mock_voice.synthesize.return_value = [mock_audio]

        long_text = " ".join(["word"] * 200)

        with patch.object(svc, "ensure_loaded", return_value=mock_voice):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with patch("app.export_audio_segment") as mock_export:
                    result = svc.synthesize(_make_request(text=long_text, output_file=Path("/tmp/test.mp3")))
        assert result == Path("/tmp/test.mp3")
        mock_export.assert_called_once()

    def test_single_chunk_no_pause(self):
        svc = PiperService(log=MagicMock())
        mock_voice = MagicMock()
        mock_audio = MagicMock()
        mock_audio.audio_int16_bytes = b"\x00\x00" * 100
        mock_audio.sample_width = 2
        mock_audio.sample_rate = 22050
        mock_audio.sample_channels = 1
        mock_voice.synthesize.return_value = [mock_audio]

        with patch.object(svc, "ensure_loaded", return_value=mock_voice):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with patch("app.export_audio_segment") as mock_export:
                    result = svc.synthesize(_make_request(text="Hello."))
        assert result == Path("/tmp/out.mp3")
        mock_export.assert_called_once()
