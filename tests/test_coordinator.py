from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import ENGINE_POCKET
from app import ENGINE_XTTS
from app import SynthesisCoordinator
from app import SynthesisRequest


def _make_request(**overrides) -> SynthesisRequest:
    defaults = {
        "text": "Hello world.",
        "language": "en",
        "output_file": Path("/tmp/out.mp3"),
        "engine": ENGINE_AUTO,
        "piper_voice_label": "English US | Lessac | medium",
        "piper_voice_code": "en_US-lessac-medium",
        "speaker_name": "Ana Florence",
        "speaker_wav": "",
    }
    defaults.update(overrides)
    return SynthesisRequest(**defaults)


@pytest.mark.unit
class TestResolveEngine:
    def test_auto_without_wav_returns_piper(self):
        req = _make_request(engine=ENGINE_AUTO, speaker_wav="")
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_PIPER

    def test_auto_with_wav_returns_xtts(self):
        req = _make_request(engine=ENGINE_AUTO, speaker_wav="/path/to/voice.wav")
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_XTTS

    def test_explicit_piper_returns_piper(self):
        req = _make_request(engine=ENGINE_PIPER)
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_PIPER

    def test_explicit_xtts_returns_xtts(self):
        req = _make_request(engine=ENGINE_XTTS)
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_XTTS

    def test_auto_with_empty_wav_string_returns_piper(self):
        req = _make_request(engine=ENGINE_AUTO, speaker_wav="")
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_PIPER

    def test_explicit_pocket_returns_pocket(self):
        req = _make_request(engine=ENGINE_POCKET)
        assert SynthesisCoordinator.resolve_engine(req) == ENGINE_POCKET


@pytest.mark.unit
class TestSynthesisCoordinatorSynthesize:
    def test_delegates_to_piper_service(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        coordinator._piper.synthesize = MagicMock(return_value=Path("/tmp/out.mp3"))
        coordinator._xtts.synthesize = MagicMock()

        result = coordinator.synthesize(_make_request(engine=ENGINE_PIPER))
        assert result == Path("/tmp/out.mp3")
        coordinator._piper.synthesize.assert_called_once()
        coordinator._xtts.synthesize.assert_not_called()

    def test_delegates_to_xtts_service(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        coordinator._xtts.synthesize = MagicMock(return_value=Path("/tmp/out.wav"))
        coordinator._piper.synthesize = MagicMock()

        result = coordinator.synthesize(_make_request(engine=ENGINE_XTTS))
        assert result == Path("/tmp/out.wav")
        coordinator._xtts.synthesize.assert_called_once()
        coordinator._piper.synthesize.assert_not_called()


@pytest.mark.unit
class TestCoordinatorSynthesizePocket:
    def test_delegates_to_pocket_service(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        coordinator._pocket.synthesize = MagicMock(return_value=Path("/tmp/out.mp3"))
        coordinator._piper.synthesize = MagicMock()
        coordinator._xtts.synthesize = MagicMock()

        result = coordinator.synthesize(_make_request(engine=ENGINE_POCKET))
        assert result == Path("/tmp/out.mp3")
        coordinator._pocket.synthesize.assert_called_once()
        coordinator._piper.synthesize.assert_not_called()
        coordinator._xtts.synthesize.assert_not_called()


@pytest.mark.unit
class TestSynthesisCoordinatorIterSegments:
    def test_delegates_to_piper(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        mock_segments = [("chunk1", MagicMock())]
        coordinator._piper.iter_segments = MagicMock(return_value=iter(mock_segments))
        coordinator._xtts.iter_segments = MagicMock()

        result = list(coordinator.iter_segments(_make_request(engine=ENGINE_PIPER)))
        assert len(result) == 1
        coordinator._piper.iter_segments.assert_called_once()
        coordinator._xtts.iter_segments.assert_not_called()

    def test_delegates_to_xtts(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        mock_segments = [("chunk1", MagicMock())]
        coordinator._xtts.iter_segments = MagicMock(return_value=iter(mock_segments))
        coordinator._piper.iter_segments = MagicMock()

        result = list(coordinator.iter_segments(_make_request(engine=ENGINE_XTTS)))
        assert len(result) == 1
        coordinator._xtts.iter_segments.assert_called_once()
        coordinator._piper.iter_segments.assert_not_called()


@pytest.mark.unit
class TestCoordinatorIterSegmentsPocket:
    def test_delegates_to_pocket(self):
        coordinator = SynthesisCoordinator(log=MagicMock())
        mock_segments = [("chunk1", MagicMock())]
        coordinator._pocket.iter_segments = MagicMock(return_value=iter(mock_segments))
        coordinator._piper.iter_segments = MagicMock()
        coordinator._xtts.iter_segments = MagicMock()

        result = list(coordinator.iter_segments(_make_request(engine=ENGINE_POCKET)))
        assert len(result) == 1
        coordinator._pocket.iter_segments.assert_called_once()
        coordinator._piper.iter_segments.assert_not_called()
        coordinator._xtts.iter_segments.assert_not_called()
