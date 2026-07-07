from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import AudioPlayer

_mock_pygame = MagicMock()
_mock_pygame.mixer.get_init.return_value = False


@pytest.mark.unit
class TestAudioPlayerEnsureReady:
    def test_first_call_initializes_pygame(self):
        player = AudioPlayer(log=MagicMock())
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.mixer.get_init.return_value = False
            player._ready = False
            player.ensure_ready()
        _mock_pygame.mixer.init.assert_called()
        assert player._ready is True

    def test_second_call_is_noop(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.ensure_ready()
        _mock_pygame.mixer.init.assert_not_called()

    def test_missing_pygame_raises(self):
        player = AudioPlayer(log=MagicMock())
        with patch.dict(sys.modules, {"pygame": None}):
            with pytest.raises(RuntimeError, match="pygame"):
                player.ensure_ready()

    def test_already_initialized_mixer_skips_init(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = False
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            _mock_pygame.mixer.get_init.return_value = True
            player.ensure_ready()
        _mock_pygame.mixer.init.assert_not_called()
        assert player._ready is True


@pytest.mark.unit
class TestAudioPlayerPlay:
    def test_sets_active_flag(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.play(Path("/tmp/test.mp3"))
        assert player._active is True
        assert player._paused is False

    def test_calls_mixer_load_and_play(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.play(Path("/tmp/test.mp3"))
        _mock_pygame.mixer.music.load.assert_called_once_with("/tmp/test.mp3")
        _mock_pygame.mixer.music.play.assert_called_once()

    def test_logs_filename(self):
        mock_log = MagicMock()
        player = AudioPlayer(log=mock_log)
        player._ready = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.play(Path("/tmp/test.mp3"))
        assert "test.mp3" in mock_log.call_args[0][0]


@pytest.mark.unit
class TestAudioPlayerPlayBlocking:
    def test_plays_then_returns_when_music_ends(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        stop_event = threading.Event()
        call_count = 0

        def busy_side_effect():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            _mock_pygame.mixer.music.get_busy.side_effect = busy_side_effect
            with patch("time.sleep", return_value=None):
                player.play_blocking(Path("/tmp/test.mp3"), stop_event)

        assert player._active is False

    def test_stops_on_stop_event(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        stop_event = threading.Event()

        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            _mock_pygame.mixer.music.get_busy.return_value = True
            with patch("time.sleep", side_effect=lambda _: stop_event.set() or None):
                player.play_blocking(Path("/tmp/test.mp3"), stop_event)

        assert player._active is False


@pytest.mark.unit
class TestAudioPlayerPause:
    def test_pauses_when_active(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        player._active = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.pause()
        _mock_pygame.mixer.music.pause.assert_called_once()
        assert player._paused is True

    def test_noop_when_not_active(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        player._active = False
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.pause()
        _mock_pygame.mixer.music.pause.assert_not_called()


@pytest.mark.unit
class TestAudioPlayerResume:
    def test_resumes_when_active(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        player._active = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.resume()
        _mock_pygame.mixer.music.unpause.assert_called_once()
        assert player._paused is False

    def test_noop_when_not_active(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        player._active = False
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.resume()
        _mock_pygame.mixer.music.unpause.assert_not_called()


@pytest.mark.unit
class TestAudioPlayerStop:
    def test_stops_when_ready(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = True
        player._active = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.stop()
        _mock_pygame.mixer.music.stop.assert_called_once()
        assert player._active is False
        assert player._paused is False

    def test_noop_when_not_ready(self):
        player = AudioPlayer(log=MagicMock())
        player._ready = False
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            _mock_pygame.reset_mock()
            player.stop()
        _mock_pygame.mixer.music.stop.assert_not_called()

    def test_respects_quiet_flag(self):
        mock_log = MagicMock()
        player = AudioPlayer(log=mock_log)
        player._ready = True
        player._active = True
        with patch.dict(sys.modules, {"pygame": _mock_pygame}):
            mock_log.reset_mock()
            _mock_pygame.reset_mock()
            player.stop(quiet=True)
        mock_log.assert_not_called()


@pytest.mark.unit
class TestAudioPlayerState:
    def test_is_active_reflects_internal_state(self):
        player = AudioPlayer(log=MagicMock())
        assert player.is_active() is False
        player._active = True
        assert player.is_active() is True

    def test_is_paused_reflects_internal_state(self):
        player = AudioPlayer(log=MagicMock())
        assert player.is_paused() is False
        player._paused = True
        assert player.is_paused() is True
