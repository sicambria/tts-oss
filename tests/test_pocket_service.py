from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import torch

from app import POCKET_VOICE_DIR
from app import PocketTTSService
from app import SynthesisRequest


def _make_request(text: str = "Hello world.", **overrides) -> SynthesisRequest:
    defaults = {
        "text": text,
        "language": "en",
        "output_file": Path("/tmp/out.mp3"),
        "engine": "Pocket TTS",
        "piper_voice_label": "",
        "piper_voice_code": "",
        "speaker_name": "alba",
        "speaker_wav": "",
        "speed": 1.0,
    }
    defaults.update(overrides)
    return SynthesisRequest(**defaults)


@pytest.mark.unit
class TestPocketServiceEnsureLoaded:
    def test_missing_import_raises(self):
        svc = PocketTTSService(log=MagicMock())
        with patch.dict("sys.modules", {"pocket_tts": None}):
            with pytest.raises(RuntimeError, match="pocket-tts is not installed"):
                svc.ensure_loaded("en")

    def test_loads_model_on_first_call(self):
        svc = PocketTTSService(log=MagicMock())
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        with patch("app.POCKET_LANG_MAP", {"en": "english"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("en")
        assert svc._model is mock_model
        assert svc._sample_rate == 24000

    def test_second_call_is_noop(self):
        svc = PocketTTSService(log=MagicMock())
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        with patch("app.POCKET_LANG_MAP", {"en": "english"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("en")
                svc.ensure_loaded("en")
        assert mock_tts.load_model.call_count == 1

    def test_language_change_reloads_model(self):
        svc = PocketTTSService(log=MagicMock())
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        with patch("app.POCKET_LANG_MAP", {"en": "english", "fr": "french"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("en")
                svc.ensure_loaded("fr")
        assert mock_tts.load_model.call_count == 2

    def test_language_change_clears_voice_states(self):
        svc = PocketTTSService(log=MagicMock())
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        with patch("app.POCKET_LANG_MAP", {"en": "english", "fr": "french"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("en")
        svc._voice_states["alba"] = {"some": "state"}
        with patch("app.POCKET_LANG_MAP", {"en": "english", "fr": "french"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("fr")
        assert len(svc._voice_states) == 0

    def test_fallback_language_uses_english(self):
        svc = PocketTTSService(log=MagicMock())
        with patch("app.POCKET_LANG_MAP", {"en": "english"}):
            with patch("pocket_tts.TTSModel") as mock_tts:
                mock_model = MagicMock()
                mock_model.sample_rate = 24000
                mock_tts.load_model.return_value = mock_model
                svc.ensure_loaded("hu")  # not in map
        mock_tts.load_model.assert_called_once_with(language="english")

    def test_unsupported_language_logs_warning(self):
        log = MagicMock()
        svc = PocketTTSService(log=log)
        with patch("app.POCKET_LANG_MAP", {"en": "english"}):
            assert svc._resolve_language("hu") == "english"
        assert any("does not support" in str(c.args[0]) for c in log.call_args_list)


@pytest.mark.unit
class TestPocketVoiceValidation:
    def test_unknown_builtin_voice_raises(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        with pytest.raises(RuntimeError, match="not a built-in Pocket TTS voice"):
            svc._get_voice_state("not_a_real_voice")

    def test_known_builtin_voice_passes_validation(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._model.get_state_for_audio_prompt.return_value = {"ok": True}
        with patch.object(PocketTTSService, "_voice_cache_path", return_value=None):
            state = svc._get_voice_state("alba")
        assert state == {"ok": True}

    def test_reference_file_skips_builtin_validation(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._model.get_state_for_audio_prompt.return_value = {"cloned": True}
        with patch.object(Path, "is_file", return_value=True):
            state = svc._get_voice_state("/tmp/my_clip.wav")
        assert state == {"cloned": True}

    def test_voice_load_failure_gives_friendly_error(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._model.get_state_for_audio_prompt.side_effect = ValueError("boom")
        with patch.object(PocketTTSService, "_voice_cache_path", return_value=None):
            with pytest.raises(RuntimeError, match="Could not load the Pocket TTS voice 'alba'"):
                svc._get_voice_state("alba")


@pytest.mark.unit
class TestPocketServiceIterSegments:
    def test_empty_text_raises(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._sample_rate = 24000
        svc._loaded_language = "english"
        with patch.object(svc, "ensure_loaded"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with pytest.raises(ValueError, match="empty"):
                    list(svc.iter_segments(_make_request(text="")))

    def test_empty_text_does_not_load_voice(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._sample_rate = 24000
        svc._loaded_language = "english"
        svc._get_voice_state = MagicMock()
        with patch.object(svc, "ensure_loaded"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with pytest.raises(ValueError, match="empty"):
                    list(svc.iter_segments(_make_request(text="")))
        svc._get_voice_state.assert_not_called()

    def test_single_chunk_with_builtin_voice(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0, 0.5, -0.5, 1.0, -1.0], dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        with patch.object(svc, "_get_voice_state", return_value={"state": "mock"}):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                results = list(svc.iter_segments(_make_request(text="Hello.")))

        assert len(results) == 1
        chunk, segment = results[0]
        assert chunk.text.strip()
        mock_model.generate_audio.assert_called_once()

    def test_multi_chunk(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 100, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        long_text = " ".join(["word"] * 200)
        with patch.object(svc, "_get_voice_state", return_value={"state": "mock"}):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                results = list(svc.iter_segments(_make_request(text=long_text)))

        assert len(results) > 1

    def test_speaker_wav_takes_priority(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 10, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        voice_states = {}
        svc._voice_states = voice_states
        getter = MagicMock(return_value={"state": "cloned"})
        svc._get_voice_state = getter

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            list(svc.iter_segments(_make_request(text="Hi.", speaker_wav="/tmp/clone.wav", speaker_name="alba")))

        getter.assert_called_once_with("/tmp/clone.wav")

    def test_speaker_name_fallback(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 10, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        getter = MagicMock(return_value={"state": "builtin"})
        svc._get_voice_state = getter

        with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
            list(svc.iter_segments(_make_request(text="Hi.", speaker_wav="", speaker_name="alba")))

        getter.assert_called_once_with("alba")

    def test_default_voice_when_no_name_given(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 10, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        getter = MagicMock(return_value={"state": "default"})
        svc._get_voice_state = getter

        with patch("app.POCKET_DEFAULT_VOICE", "alba"):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                list(svc.iter_segments(_make_request(text="Hi.", speaker_wav="", speaker_name="")))

        getter.assert_called_once_with("alba")


@pytest.mark.unit
class TestPocketServiceSynthesize:
    def test_combines_segments_with_pause(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 100, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        long_text = " ".join(["word"] * 200)
        with patch.object(svc, "_get_voice_state", return_value={"state": "mock"}):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with patch("app.export_audio_segment") as mock_export:
                    result = svc.synthesize(_make_request(text=long_text, output_file=Path("/tmp/test.mp3")))
        assert result == Path("/tmp/test.mp3")
        mock_export.assert_called_once()

    def test_single_chunk_no_pause(self):
        svc = PocketTTSService(log=MagicMock())
        mock_tensor = torch.tensor([0.0] * 100, dtype=torch.float32)
        mock_model = MagicMock()
        mock_model.sample_rate = 24000
        mock_model.generate_audio.return_value = mock_tensor
        svc._model = mock_model
        svc._sample_rate = 24000
        svc._loaded_language = "english"

        with patch.object(svc, "_get_voice_state", return_value={"state": "mock"}):
            with patch("app.AudioSegment.converter", "/fake/ffmpeg"):
                with patch("app.export_audio_segment") as mock_export:
                    result = svc.synthesize(_make_request(text="Hello."))
        assert result == Path("/tmp/out.mp3")
        mock_export.assert_called_once()


@pytest.mark.unit
class TestPocketServiceVoiceCache:
    def test_get_voice_state_uses_cache(self):
        svc = PocketTTSService(log=MagicMock())
        svc._model = MagicMock()
        svc._model.get_state_for_audio_prompt.return_value = {"cached": True}
        state = svc._get_voice_state("alba")
        assert state == {"cached": True}
        assert "alba" in svc._voice_states

    def test_get_voice_state_returns_cached(self):
        svc = PocketTTSService(log=MagicMock())
        cached = {"already": "here"}
        svc._voice_states["alba"] = cached
        result = svc._get_voice_state("alba")
        assert result is cached

    def test_voice_cache_path_returns_none_for_file(self):
        with patch.object(Path, "is_file", return_value=True):
            result = PocketTTSService._voice_cache_path("/some/file.wav")
        assert result is None

    def test_voice_cache_path_returns_path_for_builtin(self):
        with patch.object(Path, "is_file", return_value=False):
            result = PocketTTSService._voice_cache_path("alba")
        assert result is not None
        assert str(result).startswith(str(POCKET_VOICE_DIR))
        assert result.suffix == ".safetensors"
