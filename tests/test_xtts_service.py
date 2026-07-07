from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import SynthesisRequest
from app import XTTSService


def _make_request(text: str = "Hello world.", **overrides) -> SynthesisRequest:
    defaults = {
        "text": text,
        "language": "en",
        "output_file": Path("/tmp/out.mp3"),
        "engine": "XTTS v2",
        "piper_voice_label": "English US | Lessac | medium",
        "piper_voice_code": "en_US-lessac-medium",
        "speaker_name": "Ana Florence",
        "speaker_wav": "",
    }
    defaults.update(overrides)
    return SynthesisRequest(**defaults)


@pytest.mark.unit
class TestXTTSPatchTorchLoad:
    def test_patches_torch_load(self):
        svc = XTTSService(log=MagicMock())

        class FakeTorch:
            pass

        fake_torch = FakeTorch()
        calls = []

        def fake_load(*args, **kwargs):
            calls.append((args, kwargs))

        fake_torch.load = fake_load

        svc._patch_torch_load(fake_torch)

        patched = fake_torch.load
        assert patched is not fake_load

    def test_second_call_is_idempotent(self):
        svc = XTTSService(log=MagicMock())

        class FakeTorch:
            pass

        fake_torch = FakeTorch()
        fake_torch.load = MagicMock()

        svc._patch_torch_load(fake_torch)
        first = fake_torch.load
        svc._patch_torch_load(fake_torch)
        assert first is fake_torch.load

    def test_defaults_weights_only_to_false(self):
        svc = XTTSService(log=MagicMock())

        class FakeTorch:
            pass

        fake_torch = FakeTorch()
        calls = []

        def fake_load(*args, **kwargs):
            calls.append((args, kwargs))

        fake_torch.load = fake_load

        svc._patch_torch_load(fake_torch)
        fake_torch.load("model.pt", device="cpu")
        assert len(calls) == 1
        assert calls[0][1].get("weights_only") is False


@pytest.mark.unit
class TestXTTSServiceEnsureLoaded:
    def test_second_call_is_noop(self):
        svc = XTTSService(log=MagicMock())
        svc._tts = MagicMock()
        svc.ensure_loaded()

    def test_missing_import_raises(self):
        svc = XTTSService(log=MagicMock())
        with patch.dict(sys.modules, {"torch": None}):
            with pytest.raises(RuntimeError, match="Coqui TTS"):
                svc.ensure_loaded()


@pytest.mark.unit
class TestXTTSServiceIterSegments:
    def test_empty_text_raises(self):
        svc = XTTSService(log=MagicMock())
        svc._tts = MagicMock()
        with pytest.raises(ValueError, match="empty"):
            list(svc.iter_segments(_make_request(text="")))

    def test_single_chunk(self):
        svc = XTTSService(log=MagicMock())
        mock_tts = MagicMock()
        svc._tts = mock_tts
        mock_tts.tts.return_value = [0.0, 1.0, -1.0]

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            results = list(svc.iter_segments(_make_request(text="Hello.")))
        assert len(results) == 1

    def test_with_speaker_wav(self):
        svc = XTTSService(log=MagicMock())
        mock_tts = MagicMock()
        svc._tts = mock_tts
        mock_tts.tts.return_value = [0.0, 1.0, -1.0]

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            list(svc.iter_segments(_make_request(text="Hello.", speaker_wav="/path/to/speaker.wav")))
        call_kwargs = mock_tts.tts.call_args[1]
        assert "speaker_wav" in call_kwargs

    def test_without_speaker_wav_uses_speaker_name(self):
        svc = XTTSService(log=MagicMock())
        mock_tts = MagicMock()
        svc._tts = mock_tts
        mock_tts.tts.return_value = [0.0, 1.0, -1.0]

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            list(svc.iter_segments(_make_request(text="Hello.", speaker_name="Custom Speaker")))
        call_kwargs = mock_tts.tts.call_args[1]
        assert call_kwargs.get("speaker") == "Custom Speaker"


@pytest.mark.unit
class TestXTTSServiceSynthesize:
    def test_combines_segments_with_pauses(self):
        svc = XTTSService(log=MagicMock())
        mock_tts = MagicMock()
        svc._tts = mock_tts
        mock_tts.tts.return_value = [0.0] * 1000

        long_text = " ".join(["word"] * 200)

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            with patch("app.export_audio_segment") as mock_export:
                result = svc.synthesize(_make_request(text=long_text, output_file=Path("/tmp/test.mp3")))
        assert result == Path("/tmp/test.mp3")
        mock_export.assert_called_once()

    def test_returns_correct_output_path(self):
        svc = XTTSService(log=MagicMock())
        mock_tts = MagicMock()
        svc._tts = mock_tts
        mock_tts.tts.return_value = [0.0] * 100

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            with patch("app.export_audio_segment"):
                result = svc.synthesize(_make_request(text="Hi.", output_file=Path("/tmp/result.wav")))
        assert result == Path("/tmp/result.wav")
