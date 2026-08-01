from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import DEFAULT_PIPER_VOICE_LABEL
from app import PIPER_PREVIEW_TEXTS
from app import PIPER_VOICE_OPTIONS
from app import PiperVoiceWizard
from app import delete_piper_voice
from app import is_bundled_piper_voice
from app import piper_download_files
from app import piper_download_url
from app import piper_preview_text
from app import piper_sample_url
from app import piper_voice_files
from app import stream_download


class _MockVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value

    def trace_add(self, *_args: object) -> None:
        pass


@pytest.fixture
def piper_dir(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("app.PIPER_VOICE_DIR", temp_dir)
    return temp_dir


class TestPiperDownloadFiles:
    def test_filters_to_onnx_and_skips_existing(self, temp_dir: Path) -> None:
        info = {
            "files": {
                "en/en_US/lessac/medium/en_US-lessac-medium.onnx": {"size_bytes": 100},
                "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json": {"size_bytes": 50},
                "en/en_US/lessac/medium/MODEL_CARD": {"size_bytes": 200},
            }
        }
        (temp_dir / "en_US-lessac-medium.onnx").write_bytes(b"x" * 100)
        result = piper_download_files(info, temp_dir)
        assert [f.rel_path for f in result] == [
            "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
        ]
        assert result[0].local_path == temp_dir / "en_US-lessac-medium.onnx.json"
        assert result[0].size_bytes == 50

    def test_carries_sizes_and_preserves_order(self, temp_dir: Path) -> None:
        info = {
            "files": {
                "a/aa/a.onnx": {"size_bytes": 1},
                "b/bb/b.onnx.json": {"size_bytes": 2},
            }
        }
        result = piper_download_files(info, temp_dir)
        assert [(f.local_path.name, f.size_bytes) for f in result] == [
            ("a.onnx", 1),
            ("b.onnx.json", 2),
        ]

    def test_non_dict_entry_yields_zero_size(self, temp_dir: Path) -> None:
        info = {"files": {"a/aa/a.onnx": None}}
        result = piper_download_files(info, temp_dir)
        assert result[0].size_bytes == 0


class _FakeResponse:
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        self._data = data
        self.headers = headers if headers is not None else {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self, size: int) -> bytes:
        if not self._data:
            return b""
        chunk = self._data[:size]
        self._data = self._data[size:]
        return chunk


class TestStreamDownload:
    def test_writes_bytes_and_reports_monotonic_progress(self, temp_dir: Path) -> None:
        source = b"0123456789abcdef"
        dest = temp_dir / "out.onnx"
        progress: list[tuple[int, int]] = []
        response = _FakeResponse(source, {"Content-Length": str(len(source))})
        with patch("app.urlopen", return_value=response):
            stream_download("http://example/x", dest, lambda done, total: progress.append((done, total)), chunk_size=8)
        assert dest.read_bytes() == source
        assert [p[0] for p in progress] == [8, 16]
        assert progress[-1] == (len(source), len(source))

    def test_unknown_total_reports_zero(self, temp_dir: Path) -> None:
        dest = temp_dir / "out"
        progress: list[tuple[int, int]] = []
        with patch("app.urlopen", return_value=_FakeResponse(b"abc")):
            stream_download("http://example/x", dest, lambda done, total: progress.append((done, total)))
        assert dest.read_bytes() == b"abc"
        assert progress[0] == (3, 0)

    def test_malformed_content_length_is_ignored(self, temp_dir: Path) -> None:
        dest = temp_dir / "out"
        response = _FakeResponse(b"xyz", {"Content-Length": "not-a-number"})
        with patch("app.urlopen", return_value=response):
            stream_download("http://example/x", dest, lambda done, total: None)
        assert dest.read_bytes() == b"xyz"

    def test_partial_download_is_cleaned_up_on_failure(self, temp_dir: Path) -> None:
        dest = temp_dir / "out.onnx"

        class FailingResponse(_FakeResponse):
            def __init__(self, data: bytes) -> None:
                super().__init__(data)
                self._reads = 0

            def read(self, size: int) -> bytes:
                self._reads += 1
                if self._reads >= 2:
                    raise OSError("connection reset")
                return super().read(size)

        with patch("app.urlopen", return_value=FailingResponse(b"0123456789")):
            with pytest.raises(OSError):
                stream_download("http://example/x", dest, lambda done, total: None)
        assert not dest.exists()


class TestPiperSampleUrl:
    def test_from_catalog_info(self) -> None:
        info = {"language": {"code": "en_US"}, "name": "lessac", "quality": "medium"}
        url = piper_sample_url("en_US-lessac-medium", info)
        assert url == (
            "https://rhasspy.github.io/piper-samples/samples/en/en_US/lessac/medium/speaker_0.mp3"
        )

    def test_from_code_without_info(self) -> None:
        url = piper_sample_url("hu_HU-anna-medium")
        assert url == (
            "https://rhasspy.github.io/piper-samples/samples/hu/hu_HU/anna/medium/speaker_0.mp3"
        )

    def test_non_ascii_name_is_percent_encoded(self) -> None:
        info = {"language": {"code": "pt_PT"}, "name": "tugão", "quality": "medium"}
        url = piper_sample_url("pt_PT-tugão-medium", info)
        assert url == (
            "https://rhasspy.github.io/piper-samples/samples/pt/pt_PT/tug%C3%A3o/medium/speaker_0.mp3"
        )


class TestPiperDownloadUrl:
    def test_builds_huggingface_url_with_quoted_path(self) -> None:
        url = piper_download_url("en/en_US/lessac/medium/en_US-lessac-medium.onnx")
        assert url.startswith("https://huggingface.co/rhasspy/piper-voices/resolve/main/")
        assert "/en/en_US/lessac/medium/en_US-lessac-medium.onnx" in url
        assert url.endswith("?download=true")


class TestPiperPreviewText:
    def test_known_language_returns_map_entry(self) -> None:
        assert piper_preview_text("hu") == PIPER_PREVIEW_TEXTS["hu"]
        assert piper_preview_text("en") == PIPER_PREVIEW_TEXTS["en"]

    def test_unknown_language_falls_back_to_english(self) -> None:
        assert piper_preview_text("xx") == PIPER_PREVIEW_TEXTS["en"]


class TestPiperVoiceFilesAndDelete:
    def _make_voices(self, temp_dir: Path) -> None:
        for code in ("en_US-foo-medium", "en_US-bar-medium"):
            (temp_dir / f"{code}.onnx").write_bytes(b"x")
            (temp_dir / f"{code}.onnx.json").write_bytes(b"{}")

    def test_piper_voice_files_lists_only_existing(self, temp_dir: Path) -> None:
        self._make_voices(temp_dir)
        assert sorted(p.name for p in piper_voice_files("en_US-foo-medium", temp_dir)) == [
            "en_US-foo-medium.onnx",
            "en_US-foo-medium.onnx.json",
        ]
        assert piper_voice_files("en_US-ghost-medium", temp_dir) == []

    def test_delete_removes_only_requested_pair(self, temp_dir: Path) -> None:
        self._make_voices(temp_dir)
        removed = delete_piper_voice("en_US-foo-medium", temp_dir)
        assert sorted(p.name for p in removed) == [
            "en_US-foo-medium.onnx",
            "en_US-foo-medium.onnx.json",
        ]
        assert not (temp_dir / "en_US-foo-medium.onnx").exists()
        assert not (temp_dir / "en_US-foo-medium.onnx.json").exists()
        assert (temp_dir / "en_US-bar-medium.onnx").exists()

    def test_delete_tolerates_missing_and_unlink_failure(self, temp_dir: Path) -> None:
        self._make_voices(temp_dir)
        delete_piper_voice("en_US-bar-medium", temp_dir)
        assert delete_piper_voice("en_US-bar-medium", temp_dir) == []

        original_unlink = Path.unlink

        def flaky_unlink(path, *args, **kwargs):
            if path.name.endswith(".json"):
                raise OSError("locked")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", flaky_unlink):
            removed = delete_piper_voice("en_US-foo-medium", temp_dir)
        assert [p.name for p in removed] == ["en_US-foo-medium.onnx"]


class TestBundledVoice:
    def test_bundled_codes_are_protected(self) -> None:
        for metadata in PIPER_VOICE_OPTIONS.values():
            assert is_bundled_piper_voice(metadata["code"])

    def test_wizard_downloaded_code_is_not_bundled(self) -> None:
        assert not is_bundled_piper_voice("en_US-libritts-high")


class _MockApp:
    def __init__(self) -> None:
        self.root = MagicMock()
        self.settings: dict = {}
        self.service = MagicMock()
        self.player = MagicMock()
        self.reload_piper_voices = MagicMock()
        self.set_default_piper_voice = MagicMock()
        self.find_piper_label_by_code = MagicMock(return_value=None)
        self.piper_voice_options = {
            "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"},
            "English US | Lessac | medium": {"code": "en_US-lessac-medium", "xtts_language": "en"},
        }
        self.piper_voice_label = _MockVar(DEFAULT_PIPER_VOICE_LABEL)


def _make_wizard(app: _MockApp) -> tuple[PiperVoiceWizard, MagicMock]:
    mock_toplevel = MagicMock()
    with patch("app.Toplevel", return_value=mock_toplevel):
        with patch("app.StringVar", new=_MockVar):
            with patch("app.BooleanVar", new=_MockVar):
                with patch("app.threading.Thread"):
                    with patch.object(PiperVoiceWizard, "_build_ui", return_value=None):
                        wizard = PiperVoiceWizard(app)
    wizard.window = mock_toplevel
    wizard.tree = MagicMock()
    wizard.tree.get_children.return_value = []
    wizard.tree.selection.return_value = []
    wizard.download_progress = MagicMock()
    wizard.progress_text = _MockVar()
    wizard.progress_row = MagicMock()
    wizard.play_sample_button = MagicMock()
    wizard.download_button = MagicMock()
    return wizard, mock_toplevel


class TestPiperVoiceWizardDownload:
    def test_download_selected_starts_worker(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.threading.Thread") as mock_thread:
            wizard.download_selected()
        assert wizard.downloading is True
        mock_thread.assert_called_once()
        target, args = mock_thread.call_args.kwargs["target"], mock_thread.call_args.kwargs["args"]
        assert target == wizard._download_voice_worker
        assert args == ("en_US-foo-medium",)

    def test_worker_noop_when_already_installed(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, mock_toplevel = _make_wizard(app)
        code = "en_US-foo-medium"
        (piper_dir / f"{code}.onnx").write_bytes(b"x")
        (piper_dir / f"{code}.onnx.json").write_bytes(b"{}")
        wizard.catalog = {code: {"files": {f"a/{code}.onnx": {"size_bytes": 5}}}}
        wizard._download_voice_worker(code)
        callbacks = [call.args[1] for call in mock_toplevel.after.call_args_list if call.args and callable(call.args[1])]
        for callback in callbacks:
            callback()
        assert "already installed" in wizard.status.get()
        app.reload_piper_voices.assert_called_once_with(preferred_code=code)
        assert wizard.downloading is False

    def test_download_button_disabled_while_downloading(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.threading.Thread"):
            wizard.download_selected()
        wizard.download_button.configure.assert_called_once_with(state="disabled")


class TestPiperVoiceWizardDelete:
    def _installed_voice(self, piper_dir: Path, code: str) -> None:
        (piper_dir / f"{code}.onnx").write_bytes(b"x")
        (piper_dir / f"{code}.onnx.json").write_bytes(b"{}")

    def test_blocked_while_downloading(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.downloading = True
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.show_info") as mock_info:
            wizard.delete_selected()
        mock_info.assert_called_once()
        assert mock_info.call_args.args[1] == "Busy"

    def test_not_installed_shows_info(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.show_info") as mock_info:
            wizard.delete_selected()
        assert "not installed" in mock_info.call_args.args[2]

    def test_bundled_voice_is_protected(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        self._installed_voice(piper_dir, "hu_HU-anna-medium")
        wizard.tree.selection.return_value = ["hu_HU-anna-medium"]
        with patch("app.show_info") as mock_info:
            wizard.delete_selected()
        assert "Bundled voice" == mock_info.call_args.args[1]
        assert (piper_dir / "hu_HU-anna-medium.onnx").exists()

    def test_confirmed_delete_removes_files_and_refreshes(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        self._installed_voice(piper_dir, "en_US-foo-medium")
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.ask_yes_no", return_value=True):
            wizard.delete_selected()
        assert not (piper_dir / "en_US-foo-medium.onnx").exists()
        assert not (piper_dir / "en_US-foo-medium.onnx.json").exists()
        app.reload_piper_voices.assert_called_once()
        assert wizard.status.get() == "Deleted en_US-foo-medium."

    def test_cancelled_delete_keeps_files(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        self._installed_voice(piper_dir, "en_US-foo-medium")
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.ask_yes_no", return_value=False):
            wizard.delete_selected()
        assert (piper_dir / "en_US-foo-medium.onnx").exists()

    def test_delete_resets_default_when_deleted_voice_was_default(self, piper_dir: Path) -> None:
        app = _MockApp()
        app.settings = {"default_piper_voice_label": "English US | Foo | medium"}
        app.find_piper_label_by_code.return_value = "English US | Foo | medium"
        wizard, _toplevel = _make_wizard(app)
        self._installed_voice(piper_dir, "en_US-foo-medium")
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.ask_yes_no", return_value=True):
            wizard.delete_selected()
        app.set_default_piper_voice.assert_called_once_with(DEFAULT_PIPER_VOICE_LABEL)


class TestPiperVoiceWizardPreview:
    def test_play_sample_not_installed_shows_info(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.show_info") as mock_info:
            with patch("app.threading.Thread") as mock_thread:
                wizard.play_sample()
        assert "not installed" in mock_info.call_args.args[2]
        mock_thread.assert_not_called()

    def test_play_sample_starts_preview_worker(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        (piper_dir / "en_US-foo-medium.onnx").write_bytes(b"x")
        (piper_dir / "en_US-foo-medium.onnx.json").write_bytes(b"{}")
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.threading.Thread") as mock_thread:
            wizard.play_sample()
        assert wizard.previewing is True
        target, args = mock_thread.call_args.kwargs["target"], mock_thread.call_args.kwargs["args"]
        assert target == wizard._preview_worker
        assert args[0] == "en_US-foo-medium"
        assert isinstance(args[1], type(wizard.preview_stop_event))

    def test_play_sample_while_previewing_stops(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.previewing = True
        wizard.preview_stop_event = __import__("threading").Event()
        with patch("app.threading.Thread") as mock_thread:
            wizard.play_sample()
        app.player.stop.assert_called_once_with(quiet=True)
        mock_thread.assert_not_called()


class TestPiperVoiceWizardOpenSample:
    def test_open_sample_page_uses_derived_url(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.webbrowser.open_new_tab") as mock_open:
            wizard.open_sample_page()
        mock_open.assert_called_once_with(piper_sample_url("en_US-foo-medium", {}))

    def test_open_sample_page_reports_failure(self, piper_dir: Path) -> None:
        app = _MockApp()
        wizard, _toplevel = _make_wizard(app)
        wizard.tree.selection.return_value = ["en_US-foo-medium"]
        with patch("app.webbrowser.open_new_tab", side_effect=OSError("no browser")):
            with patch("app.show_error") as mock_error:
                wizard.open_sample_page()
        mock_error.assert_called_once()
        assert "Unable to Open Sample" == mock_error.call_args.args[1]
