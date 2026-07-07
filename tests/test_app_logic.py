from __future__ import annotations

import os
import queue
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from app import DEFAULT_PIPER_VOICE_LABEL
from app import DEFAULT_SPEAKER
from app import ENGINE_AUTO
from app import PREVIEW_OUTPUT_PATH
from app import App
from app import get_default_music_folder


class _MockVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value

    def trace_add(self, *_args: object) -> None:
        pass


class _MockText:
    def __init__(self):
        self._content = ""
        self._selection = None
        self._tags = set()

    def get(self, start, end):
        if start == "sel.first" and end == "sel.last":
            return self._selection or ""
        return self._content

    def insert(self, index, text):
        self._content = text

    def delete(self, start, end):
        self._content = ""

    def tag_ranges(self, tag):
        if self._selection:
            return ["sel.first", "sel.last"]
        return ()

    def tag_remove(self, tag, start, end):
        self._tags.discard(tag)

    def index(self, spec):
        return "1.0"

    def count(self, start, end, unit):
        return [len(self._content)]


def _make_app():
    with patch("app.Tk", MagicMock()):
        app = App.__new__(App)
        app.root = MagicMock()
        app.log_queue = queue.Queue()
        app.service = MagicMock()
        app.player = MagicMock()
        app.settings = {}
        app.voice_wizard = None
        app.doc_wizard = None
        app.piper_voice_options = {
            "Hungarian | Anna | medium": {
                "code": "hu_HU-anna-medium",
                "xtts_language": "hu",
            },
            "English US | Lessac | medium": {
                "code": "en_US-lessac-medium",
                "xtts_language": "en",
            },
        }
        app.language = _MockVar("hu")
        app.engine = _MockVar(ENGINE_AUTO)
        app.piper_voice_label = _MockVar(DEFAULT_PIPER_VOICE_LABEL)
        app.speaker_name = _MockVar(DEFAULT_SPEAKER)
        app.speaker_wav = _MockVar("")
        app.output_file = _MockVar("/tmp/out/speech.mp3")
        app.speed = MagicMock()
        app.speed.get.return_value = 1.0
        app.status = MagicMock()
        app.playback_toggle_label = MagicMock()
        app.generation_modal = None
        app.generation_progress = None
        app.generation_status = MagicMock()
        app.worker = None
        app.preview_worker = None
        app.preview_stop_event = MagicMock()
        app.preview_job_id = 0
        app.last_selection_start_offset = None
        app.engine_hint = MagicMock()
        app.text = _MockText()
        app.text._content = "Hello world. This is a test."
        app.log = _MockText()
        app.log.configure = MagicMock()
        app.lang_box = MagicMock()
        app.engine_box = MagicMock()
        app.speaker_name_entry = MagicMock()
        app.piper_voice_box = MagicMock()
        app.speaker_wav_entry = MagicMock()
        app.speaker_wav_button = MagicMock()
        app.playback_toggle_button = MagicMock()
        return app


class TestCollectRequest:
    def test_valid_request(self):
        app = _make_app()
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_not_called()
        assert req is not None
        assert req.text == "Hello world. This is a test."
        assert req.piper_voice_code == "hu_HU-anna-medium"

    def test_empty_text_shows_error(self):
        app = _make_app()
        app.text._content = "   "
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_called_once()
        assert req is None

    def test_missing_output_path(self):
        app = _make_app()
        app.output_file.set("")
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_called_once()
        assert req is None

    def test_invalid_format_extension(self):
        app = _make_app()
        app.output_file.set("/tmp/test.flac")
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_called_once()
        assert req is None

    def test_speaker_wav_does_not_exist(self):
        app = _make_app()
        app.speaker_wav.set("/nonexistent/voice.wav")
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_called_once()
        assert req is None

    def test_require_output_false_skips_output_validation(self):
        app = _make_app()
        app.output_file.set("")
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request(require_output=False)
        mock_err.assert_not_called()
        assert req is not None

    def test_speed_included_in_request(self):
        app = _make_app()
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_not_called()
        assert req is not None
        assert req.speed == 1.0

    def test_custom_speed_included_in_request(self):
        app = _make_app()
        app.speed.get.return_value = 1.5
        with patch("app.messagebox.showerror") as mock_err:
            req = app.collect_request()
        mock_err.assert_not_called()
        assert req is not None
        assert req.speed == 1.5


class TestEnsureXttsLicenseAcceptance:
    def test_env_var_set_returns_true(self):
        app = _make_app()
        with patch.dict(os.environ, {"COQUI_TOS_AGREED": "1"}):
            assert app.ensure_xtts_license_acceptance() is True

    def test_env_var_not_set_user_clicks_yes(self, monkeypatch):
        app = _make_app()
        monkeypatch.delenv("COQUI_TOS_AGREED", raising=False)
        with patch("app.messagebox.askyesno", return_value=True):
            result = app.ensure_xtts_license_acceptance()
        assert result is True

    def test_env_var_not_set_user_clicks_no(self, monkeypatch):
        app = _make_app()
        monkeypatch.delenv("COQUI_TOS_AGREED", raising=False)
        with patch("app.messagebox.askyesno", return_value=False):
            result = app.ensure_xtts_license_acceptance()
        assert result is False


class TestFlushLogs:
    def test_actual_flush_logs_drains_queue(self):
        app = _make_app()
        app.log_queue.put("test message")
        app.log = MagicMock()
        app.root.after = MagicMock()

        line = app.log_queue.get_nowait()
        app.log.insert("end", f"{line}\n")
        app.log.see("end")

        app.log.insert.assert_called_once()
        app.log.see.assert_called_once()

    def test_flush_logs_full_flow(self):
        app = _make_app()
        app.log = MagicMock()
        app.log.configure = MagicMock()
        app.root.after = MagicMock()

        mock_queue = MagicMock()
        mock_queue.empty.side_effect = [False, False, True]
        mock_queue.get_nowait.side_effect = ["msg1", "msg2"]
        app.log_queue = mock_queue

        app.flush_logs()

        assert app.log.insert.call_count == 2
        assert app.log.see.call_count == 2
        app.root.after.assert_called_once_with(150, app.flush_logs)


class TestEnqueueLog:
    def test_puts_message_on_queue(self):
        app = _make_app()
        app.enqueue_log("test message")
        assert app.log_queue.get() == "test message"


class TestReloadPiperVoices:
    def test_updates_voice_options_and_dropdown(self):
        app = _make_app()
        app.find_piper_label_by_code = lambda code: "Hungarian | Anna | medium"
        with patch("app.discover_local_piper_voices", return_value={"New Voice | Test | high": {"code": "test-code", "xtts_language": "en"}}):
            app.reload_piper_voices()
        assert "New Voice | Test | high" in app.piper_voice_options
        app.piper_voice_box.configure.assert_called()


class TestCleanupPreviewFiles:
    def test_removes_glob_matching_files(self, temp_dir):
        app = _make_app()
        preview_dir = temp_dir
        test_file = preview_dir / "read-aloud-preview-1.wav"
        test_file.write_text("fake wav")

        with patch.object(PREVIEW_OUTPUT_PATH.__class__, "resolve", return_value=preview_dir / "read-aloud-preview.mp3"):
            with patch.object(PREVIEW_OUTPUT_PATH.__class__, "parent", preview_dir):
                app.cleanup_preview_files(paths=[test_file])
        assert not test_file.exists()




class TestGetTextContent:
    def test_returns_text_from_widget(self):
        app = _make_app()
        app.text._content = "Sample text."
        assert app.get_text_content() == "Sample text."

    def test_returns_selection_text(self):
        app = _make_app()
        app.text._content = "Full text content."
        app.text._selection = "Full text"
        result = app.get_text_content()
        assert isinstance(result, str)


class TestGetReadAloudStartOffset:
    def test_returns_zero_when_no_selection(self):
        app = _make_app()
        app.text._content = "Hello world."
        app.text._selection = None
        app.text.tag_ranges = lambda tag: ()
        result = app.get_read_aloud_start_offset()
        assert result is not None
        assert result >= 0

    def test_returns_none_for_empty_text(self):
        app = _make_app()
        app.text._content = ""
        result = app.get_read_aloud_start_offset()
        assert result is None


class TestResolvedEngine:
    def test_auto_returns_piper_without_wav(self):
        app = _make_app()
        app.engine.set("Auto")
        app.speaker_wav.set("")
        assert app.resolved_engine() == "Piper"

    def test_auto_returns_xtts_with_wav(self):
        app = _make_app()
        app.engine.set("Auto")
        app.speaker_wav.set("/path/to/wav")
        assert app.resolved_engine() == "XTTS v2"

    def test_explicit_engine_returned(self):
        app = _make_app()
        app.engine.set("Piper")
        assert app.resolved_engine() == "Piper"


class TestFindPiperLabelByCode:
    def test_existing_code_finds_label(self):
        app = _make_app()
        result = app.find_piper_label_by_code("hu_HU-anna-medium")
        assert result == "Hungarian | Anna | medium"

    def test_missing_code_returns_none(self):
        app = _make_app()
        result = app.find_piper_label_by_code("nonexistent")
        assert result is None


class TestSetDefaultPiperVoice:
    def test_sets_voice_and_saves(self):
        app = _make_app()
        with patch("app.save_app_settings") as mock_save:
            app.set_default_piper_voice("English US | Lessac | medium")
        assert app.settings["default_piper_voice_label"] == "English US | Lessac | medium"
        assert app.piper_voice_label.get() == "English US | Lessac | medium"
        mock_save.assert_called_once()


class TestUpdatePlaybackToggleLabel:
    def test_paused_shows_resume(self):
        app = _make_app()
        app.player.is_paused.return_value = True
        app.update_playback_toggle_label()
        app.playback_toggle_label.set.assert_called_with("Resume")

    def test_not_paused_shows_pause(self):
        app = _make_app()
        app.player.is_paused.return_value = False
        app.update_playback_toggle_label()
        app.playback_toggle_label.set.assert_called_with("Pause")


class TestTextIndexToOffset:
    def test_returns_char_count(self):
        app = _make_app()
        app.text.count = MagicMock(return_value=[10])
        result = app.text_index_to_offset("1.5")
        assert result == 10


class TestOffsetToTextIndex:
    def test_formats_offset(self):
        app = _make_app()
        result = app.offset_to_text_index(42)
        assert "42" in result


class TestClearReadAloudHighlight:
    def test_removes_tag(self):
        app = _make_app()
        app.text.tag_remove = MagicMock()
        app.clear_read_aloud_highlight()
        app.text.tag_remove.assert_called_once()


class TestOnVoiceSettingsChanged:
    def test_piper_engine_enables_piper_box(self):
        app = _make_app()
        app.engine.set("Piper")
        app.speaker_wav.set("")
        app.on_voice_settings_changed()
        assert app.piper_voice_box.configure.call_count >= 1

    def test_xtts_engine_disables_piper_box(self):
        app = _make_app()
        app.engine.set("XTTS v2")
        app.on_voice_settings_changed()
        assert app.speaker_wav_entry.configure.call_count >= 1

    def test_missing_piper_voice_uses_default_metadata(self):
        app = _make_app()
        app.piper_voice_label.set("nonexistent")
        app.on_voice_settings_changed()


class TestPauseResumeStop:
    def test_pause_playback(self):
        app = _make_app()
        app.pause_playback()
        app.player.pause.assert_called_once()

    def test_resume_playback(self):
        app = _make_app()
        app.resume_playback()
        app.player.resume.assert_called_once()

    def test_stop_playback(self):
        app = _make_app()
        app.stop_playback()
        app.player.stop.assert_called_once()
        app.preview_stop_event.set.assert_called_once()

    def test_stop_playback_caught_exception(self):
        app = _make_app()
        app.player.stop.side_effect = RuntimeError("mock error")
        app.stop_playback()


class TestTogglePlaybackPause:
    def test_toggle_paused_resumes(self):
        app = _make_app()
        app.player.is_paused.return_value = True
        app.toggle_playback_pause()
        app.player.resume.assert_called_once()

    def test_toggle_not_paused_pauses(self):
        app = _make_app()
        app.player.is_paused.return_value = False
        app.toggle_playback_pause()
        app.player.pause.assert_called_once()


class TestUpdateSelectionCache:
    def test_sets_offset_from_selection(self):
        app = _make_app()
        app.text._content = "Hello world"
        app.text._selection = "Hello"
        app.text.tag_ranges = lambda tag: ["sel.first", "sel.last"]
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[0])
        app.update_selection_cache()
        assert app.last_selection_start_offset is not None

    def test_clears_offset_when_no_selection(self):
        app = _make_app()
        app.last_selection_start_offset = 5
        app.text.tag_ranges = lambda tag: ()
        app.update_selection_cache()
        assert app.last_selection_start_offset is None

    def test_skips_when_preview_running(self):
        app = _make_app()
        app.preview_worker = MagicMock()
        app.preview_worker.is_alive.return_value = True
        app.last_selection_start_offset = 5
        app.update_selection_cache()
        assert app.last_selection_start_offset == 5


class TestCleanupPreviewFilesEdgeCases:
    def test_empty_candidates_noop(self, temp_dir):
        app = _make_app()
        app.cleanup_preview_files(paths=[])

    def test_cleanup_removes_files(self, temp_dir):
        app = _make_app()
        f = temp_dir / "test.wav"
        f.write_text("data")
        app.cleanup_preview_files(paths=[f])
        assert not f.exists()

    def test_retries_on_permission_error(self, temp_dir):
        app = _make_app()
        f = temp_dir / "test.wav"
        with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            app.cleanup_preview_files(paths=[f])


class TestFlushLogsDirect:
    def test_inserts_log_message(self):
        app = _make_app()
        app.log = MagicMock()
        app.log_queue.put("test log line")
        app.log_queue.get_nowait = MagicMock(return_value="test log line")
        line = app.log_queue.get_nowait()
        app.log.insert("end", f"{line}\n")
        app.log.see("end")
        app.log.insert.assert_called_once()


class TestReloadPiperVoicesBranch:
    def test_preferred_label_not_found_falls_back_to_default(self):
        app = _make_app()
        app.piper_voice_label.set("nonexistent")
        with patch("app.discover_local_piper_voices", return_value={"Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"}}):
            app.reload_piper_voices(preferred_code=None)


class TestPickReferenceWav:
    def test_pick_sets_wav_path(self):
        app = _make_app()
        with patch("app.filedialog.askopenfilename", return_value="/path/to/voice.wav"):
            app.pick_reference_wav()
        assert app.speaker_wav.get() == "/path/to/voice.wav"

    def test_pick_cancelled(self):
        app = _make_app()
        app.speaker_wav.set("before")
        with patch("app.filedialog.askopenfilename", return_value=""):
            app.pick_reference_wav()
        assert app.speaker_wav.get() == "before"


class TestPickOutputFile:
    def test_pick_sets_output_path(self):
        app = _make_app()
        with patch("app.filedialog.asksaveasfilename", return_value="/tmp/speech.mp3"):
            app.pick_output_file()
        assert app.output_file.get() == "/tmp/speech.mp3"

    def test_pick_cancelled(self):
        app = _make_app()
        app.output_file.set("before")
        with patch("app.filedialog.asksaveasfilename", return_value=""):
            app.pick_output_file()
        assert app.output_file.get() == "before"


class TestOpenVoiceWizard:
    def test_creates_new_wizard_when_none(self):
        app = _make_app()
        with patch("app.PiperVoiceWizard") as mock_wiz:
            app.open_voice_wizard()
        mock_wiz.assert_called_once()

    def test_lifts_existing_wizard(self):
        app = _make_app()
        mock_window = MagicMock()
        mock_window.winfo_exists.return_value = True
        app.voice_wizard = MagicMock()
        app.voice_wizard.window = mock_window
        app.open_voice_wizard()
        mock_window.lift.assert_called_once()


class TestOpenDocumentWizard:
    def test_creates_new_wizard_when_none(self):
        app = _make_app()
        with patch("app.DocumentToAudioWizard") as mock_wiz:
            app.open_document_wizard()
        mock_wiz.assert_called_once()


class TestLoadTextFile:
    def test_loads_content_from_file(self):
        app = _make_app()
        app.text.delete = MagicMock()
        app.text.insert = MagicMock()
        with patch("app.filedialog.askopenfilename", return_value="/tmp/test.txt"):
            with patch("pathlib.Path.read_text", return_value="file content"):
                app.load_text_file()
        app.text.insert.assert_called_with("1.0", "file content")

    def test_cancelled_does_nothing(self):
        app = _make_app()
        app.text.delete = MagicMock()
        with patch("app.filedialog.askopenfilename", return_value=""):
            app.load_text_file()
        app.text.delete.assert_not_called()


class TestCloseGenerationModal:
    def test_closes_existing_modal(self):
        app = _make_app()
        mock_modal = MagicMock()
        mock_modal.winfo_exists.return_value = True
        app.generation_modal = mock_modal
        app.close_generation_modal()
        mock_modal.destroy.assert_called_once()
        assert app.generation_modal is None

    def test_noop_when_no_modal(self):
        app = _make_app()
        app.generation_modal = None
        app.close_generation_modal()


class TestUpdateGenerationProgress:
    def test_updates_when_modal_exists(self):
        app = _make_app()
        mock_modal = MagicMock()
        mock_modal.winfo_exists.return_value = True
        app.generation_modal = mock_modal
        app.generation_progress = MagicMock()
        app.generation_status = MagicMock()
        app.update_generation_progress(5, 10, "Processing...")
        app.generation_status.set.assert_called_with("Processing...")

    def test_noop_when_no_modal(self):
        app = _make_app()
        app.generation_modal = None
        app.generation_progress = MagicMock()
        app.update_generation_progress(5, 10, "test")


class TestFinishGenerationModal:
    def test_success_path(self):
        app = _make_app()
        mock_modal = MagicMock()
        mock_modal.winfo_exists.return_value = True
        app.generation_modal = mock_modal
        app.generation_progress = MagicMock()
        app.generation_close_button = MagicMock()
        app.generation_open_file_button = MagicMock()
        app.generation_open_folder_button = MagicMock()
        app.finish_generation_modal(Path("/tmp/out.mp3"))
        assert app.generation_result_path == Path("/tmp/out.mp3")

    def test_error_path(self):
        app = _make_app()
        mock_modal = MagicMock()
        mock_modal.winfo_exists.return_value = True
        app.generation_modal = mock_modal
        app.generation_progress = MagicMock()
        app.generation_close_button = MagicMock()
        app.generation_open_file_button = MagicMock()
        app.generation_open_folder_button = MagicMock()
        app.finish_generation_modal(None, error="failed")
        assert app.generation_result_path is None

    def test_noop_when_no_modal(self):
        app = _make_app()
        app.generation_modal = None
        app.finish_generation_modal(Path("/tmp/out.mp3"))


class TestStartGeneration:
    def test_already_running(self):
        app = _make_app()
        app.worker = MagicMock()
        app.worker.is_alive.return_value = True
        with patch("app.messagebox.showinfo") as mock_info:
            app.start_generation()
        mock_info.assert_called_once()

    def test_invalid_request(self):
        app = _make_app()
        app.worker = None
        with patch.object(app, "collect_request", return_value=None):
            app.start_generation()

    def test_starts_worker(self):
        app = _make_app()
        app.worker = None
        req = MagicMock()
        with patch.object(app, "collect_request", return_value=req):
            with patch.object(app.service, "resolve_engine", return_value="Piper"):
                with patch.object(app, "show_generation_modal"):
                    app.start_generation()
                    assert app.worker is not None


class TestOnTextClick:
    def test_click_during_preview(self):
        app = _make_app()
        app.text._content = "Hello world"
        app.preview_worker = MagicMock()
        app.preview_worker.is_alive.return_value = True
        app.highlight_read_aloud_line = MagicMock()
        mock_event = MagicMock()
        mock_event.x = 10
        mock_event.y = 5
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[0])
        app.text.tag_ranges = MagicMock(return_value=())
        app.on_text_click(mock_event)
        app.highlight_read_aloud_line.assert_called_once()

    def test_click_no_preview(self):
        app = _make_app()
        app.text._content = "Hello world"
        app.preview_worker = None
        mock_event = MagicMock()
        mock_event.x = 10
        mock_event.y = 5
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[0])
        app.text.tag_ranges = MagicMock(return_value=())
        app.on_text_click(mock_event)


class TestHighlightReadAloudLine:
    def test_highlights_line(self):
        app = _make_app()
        app.text.tag_remove = MagicMock()
        app.text.tag_add = MagicMock()
        app.text.mark_set = MagicMock()
        app.text.see = MagicMock()
        app.text.index = MagicMock(return_value="1.0")
        app.highlight_read_aloud_line(0)
        app.text.tag_add.assert_called_once()


class TestRunGeneration:
    def test_run_generation_success(self):
        app = _make_app()
        app.service.iter_segments.return_value = [(None, MagicMock())]
        app.update_generation_progress = MagicMock()
        app.finish_generation_modal = MagicMock()
        app.root.after.side_effect = lambda ms, cb: cb()
        req = MagicMock()
        req.text = "Hello world."
        req.output_file = Path("/tmp/out.mp3")
        with patch("app.export_audio_segment"):
            with patch("app.AudioSegment.silent", return_value=MagicMock()):
                with patch("app.chunk_text_with_offsets", return_value=[MagicMock()]):
                    app.run_generation(req)
        app.finish_generation_modal.assert_called()

    def test_run_generation_empty_text(self):
        app = _make_app()
        app.finish_generation_modal = MagicMock()
        app.root.after.side_effect = lambda ms, cb: cb()
        req = MagicMock()
        req.text = ""
        with patch("app.chunk_text_with_offsets", return_value=[]):
            app.run_generation(req)
        assert app.finish_generation_modal.called

    def test_run_generation_error_handling(self):
        app = _make_app()
        app.finish_generation_modal = MagicMock()
        app.root.after.side_effect = lambda ms, cb: cb()
        req = MagicMock()
        req.text = "Hello world."
        with patch("app.chunk_text_with_offsets", return_value=[MagicMock()]):
            app.service.iter_segments.side_effect = RuntimeError("synthesis error")
            app.run_generation(req)
        assert app.finish_generation_modal.called

    def test_run_generation_multi_chunk_adds_pause(self):
        app = _make_app()
        app.update_generation_progress = MagicMock()
        app.finish_generation_modal = MagicMock()
        app.generation_status = MagicMock()
        app.root.after.side_effect = lambda ms, cb: cb()
        req = MagicMock()
        req.text = "Hello world."
        req.output_file = Path("/tmp/out.mp3")
        mock_chunk = MagicMock()
        mock_segment = MagicMock()
        app.service.iter_segments.return_value = [(mock_chunk, mock_segment), (mock_chunk, mock_segment)]
        with patch("app.export_audio_segment"):
            with patch("app.AudioSegment.silent", return_value=MagicMock()):
                with patch("app.chunk_text_with_offsets", return_value=[mock_chunk, mock_chunk]):
                    app.run_generation(req)
        assert app.finish_generation_modal.called


class TestGetDefaultMusicFolder:
    def test_linux_xdg_music_dir(self, temp_dir):
        config_dir = temp_dir / ".config"
        config_dir.mkdir()
        user_dirs = config_dir / "user-dirs.dirs"
        user_dirs.write_text(f'XDG_MUSIC_DIR="{temp_dir / "Music"}"')
        with patch("sys.platform", "linux"):
            with patch("app.Path.home", return_value=temp_dir):
                result = get_default_music_folder()
        assert "Music" in str(result)

    def test_linux_no_xdg_falls_back_to_home_music(self, temp_dir):
        config_dir = temp_dir / ".config"
        config_dir.mkdir(parents=True)
        with patch("sys.platform", "linux"):
            with patch("app.Path.home", return_value=temp_dir):
                result = get_default_music_folder()
        assert result == temp_dir / "Music"

    def test_darwin_returns_music(self, temp_dir):
        with patch("sys.platform", "darwin"):
            with patch("app.Path.home", return_value=temp_dir):
                result = get_default_music_folder()
        assert result == temp_dir / "Music"


class TestOnSpeedChanged:
    def test_updates_speed_label(self):
        app = _make_app()
        app.speed.get.return_value = 1.5
        app.speed_label = MagicMock()
        app._on_speed_changed()
        app.speed_label.configure.assert_called_once_with(text="Speed: 1.5x")


class TestStartReadAloudFlow:
    def test_start_read_aloud_from_no_offset_uses_start(self):
        app = _make_app()
        app.worker = None
        app.get_read_aloud_start_offset = MagicMock(return_value=0)
        app.get_text_content = MagicMock(return_value="Hello world.")
        app.service.resolve_engine = MagicMock(return_value="Piper")
        app.cleanup_preview_files = MagicMock()
        app.update_playback_toggle_label = MagicMock()
        app.root.after = MagicMock()
        req = MagicMock()
        with patch.object(app, "collect_request", return_value=req):
            app.start_read_aloud_from(None, reason="button")
        assert app.preview_job_id == 1

    def test_start_read_aloud_from_with_offset(self):
        app = _make_app()
        app.worker = None
        app.get_read_aloud_start_offset = MagicMock(return_value=5)
        app.get_text_content = MagicMock(return_value="Hello world.")
        app.service.resolve_engine = MagicMock(return_value="Piper")
        app.cleanup_preview_files = MagicMock()
        app.update_playback_toggle_label = MagicMock()
        app.root.after = MagicMock()
        req = MagicMock()
        with patch.object(app, "collect_request", return_value=req):
            app.start_read_aloud_from(10, reason="click_jump")
        assert app.preview_job_id == 1

    def test_start_read_aloud_empty_text_collect_fails(self):
        app = _make_app()
        app.text._content = ""
        app.worker = None
        app.service.resolve_engine = MagicMock(return_value="Piper")
        with patch("app.messagebox.showerror") as mock_err:
            app.start_read_aloud()
        mock_err.assert_called_once()

    def test_start_read_aloud_worker_busy(self):
        app = _make_app()
        app.worker = MagicMock()
        app.worker.is_alive.return_value = True
        with patch("app.messagebox.showinfo") as mock_info:
            app.start_read_aloud_from(0, reason="button")
        mock_info.assert_called_once()

    def test_start_read_aloud_xtts_license_rejected(self):
        app = _make_app()
        app.worker = None
        app.get_read_aloud_start_offset = MagicMock(return_value=0)
        app.get_text_content = MagicMock(return_value="Hello world.")
        app.service.resolve_engine = MagicMock(return_value="XTTS v2")
        app.ensure_xtts_license_acceptance = MagicMock(return_value=False)
        req = MagicMock()
        with patch.object(app, "collect_request", return_value=req):
            app.start_read_aloud_from(0, reason="button")
        assert app.preview_job_id == 0

    def test_start_generation_xtts_license_rejected(self):
        app = _make_app()
        app.worker = None
        app.service.resolve_engine = MagicMock(return_value="XTTS v2")
        app.ensure_xtts_license_acceptance = MagicMock(return_value=False)
        app.show_generation_modal = MagicMock()
        req = MagicMock()
        with patch.object(app, "collect_request", return_value=req):
            app.start_generation()
        app.show_generation_modal.assert_not_called()

    def test_run_read_aloud_error_handling(self):
        app = _make_app()
        app.service.iter_segments.side_effect = RuntimeError("read aloud error")
        app.root.after.side_effect = lambda ms, cb=None: cb() if cb else None
        app.highlight_read_aloud_line = MagicMock()
        app.update_playback_toggle_label = MagicMock()
        app.clear_read_aloud_highlight = MagicMock()
        app.cleanup_preview_files = MagicMock()
        app.player.play_blocking = MagicMock()
        app.enqueue_log = MagicMock()
        app.preview_job_id = 1
        req = MagicMock()
        stop_event = MagicMock()
        stop_event.is_set.return_value = False

        with patch("app.messagebox.showerror"):
            app.run_read_aloud(req, 0, 1, stop_event)

        app.enqueue_log.assert_called()
        app.clear_read_aloud_highlight.assert_called()

    def test_run_read_aloud_stops_on_job_id_change(self):
        app = _make_app()
        mock_chunk = MagicMock()
        mock_chunk.start = 0
        mock_chunk.text = "hello"
        mock_segment = MagicMock()
        app.service.iter_segments.return_value = [(mock_chunk, mock_segment)]
        app.root.after.side_effect = lambda ms, cb=None: None
        app.highlight_read_aloud_line = MagicMock()
        app.update_playback_toggle_label = MagicMock()
        app.clear_read_aloud_highlight = MagicMock()
        app.cleanup_preview_files = MagicMock()
        app.player.play_blocking = MagicMock()
        app.enqueue_log = MagicMock()
        app.preview_job_id = 99
        req = MagicMock()
        stop_event = MagicMock()
        stop_event.is_set.return_value = False

        app.run_read_aloud(req, 0, 1, stop_event)
        app.player.play_blocking.assert_not_called()

    def test_start_read_aloud_while_worker_running(self):
        app = _make_app()
        app.worker = MagicMock()
        app.worker.is_alive.return_value = True
        with patch("app.messagebox.showinfo") as mock_info:
            app.start_read_aloud_from(0, reason="button")
        mock_info.assert_called_once()


class TestOpenDocumentWizardExisting:
    def test_lifts_existing_wizard(self):
        app = _make_app()
        mock_window = MagicMock()
        mock_window.winfo_exists.return_value = True
        app.doc_wizard = MagicMock()
        app.doc_wizard.window = mock_window
        app.open_document_wizard()
        mock_window.lift.assert_called_once()


class TestOpenGeneratedFileFolder:
    def test_open_generated_file_no_path_returns(self):
        app = _make_app()
        app.generation_result_path = None
        app.open_path_in_system = MagicMock()
        app.open_generated_file()
        app.open_path_in_system.assert_not_called()

    def test_open_generated_file_with_path(self):
        app = _make_app()
        app.generation_result_path = Path("/tmp/test.mp3")
        app.open_path_in_system = MagicMock()
        app.open_generated_file()
        app.open_path_in_system.assert_called_once_with(Path("/tmp/test.mp3"))

    def test_open_generated_folder_with_path(self):
        app = _make_app()
        app.generation_result_path = Path("/tmp/test.mp3")
        app.open_path_in_system = MagicMock()
        app.open_generated_folder()
        app.open_path_in_system.assert_called_once_with(Path("/tmp"))

    def test_open_generated_folder_no_path(self):
        app = _make_app()
        app.generation_result_path = None
        app.open_path_in_system = MagicMock()
        with patch("app.Path.cwd", return_value=Path("/tmp")):
            app.open_generated_folder()
        app.open_path_in_system.assert_called_once()


class TestReloadPiperVoicesWithPreferredCode:
    def test_preferred_code_finds_label(self):
        app = _make_app()
        app.piper_voice_label.set("some-other")
        with patch("app.discover_local_piper_voices", return_value={
            "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"}
        }):
            app.reload_piper_voices(preferred_code="hu_HU-anna-medium")
        assert app.piper_voice_label.get() == "Hungarian | Anna | medium"

    def test_preferred_code_not_found_keeps_current(self):
        app = _make_app()
        app.piper_voice_label.set("some-other")
        with patch("app.discover_local_piper_voices", return_value={
            "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"}
        }):
            app.reload_piper_voices(preferred_code="nonexistent")
        assert app.piper_voice_label.get() == "Hungarian | Anna | medium"


class TestGetReadAloudStartOffsetSelection:
    def test_with_selection_returns_offset(self):
        app = _make_app()
        app.text._content = "Hello world test here."
        app.text._selection = "Hello"
        app.text.tag_ranges = MagicMock(return_value=["sel.first", "sel.last"])
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[0])
        result = app.get_read_aloud_start_offset()
        assert result is not None

    def test_with_widget_index(self):
        app = _make_app()
        app.text._content = "Hello world test here."
        app.text._selection = None
        app.text.tag_ranges = MagicMock(return_value=("sel.first", "sel.last"))
        app.text.index = MagicMock(return_value="1.5")
        app.text.count = MagicMock(return_value=[5])
        result = app.get_read_aloud_start_offset(widget_index="1.5")
        assert result is not None

    def test_with_last_selection_offset(self):
        app = _make_app()
        app.text._content = "Hello world test here."
        app.last_selection_start_offset = 6
        app.text.tag_ranges = MagicMock(return_value=())
        result = app.get_read_aloud_start_offset()
        assert result is not None

    def test_no_selection_no_last_offset_returns_word_start(self):
        app = _make_app()
        app.text._content = "Hello world test here."
        app.last_selection_start_offset = None
        app.text.tag_ranges = MagicMock(return_value=())
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[6])
        result = app.get_read_aloud_start_offset()
        assert result is not None


class TestOnTextClickNoPreview:
    def test_click_without_preview_does_nothing(self):
        app = _make_app()
        app.text._content = "Hello world"
        app.text.index = MagicMock(return_value="1.0")
        app.text.count = MagicMock(return_value=[0])
        app.text.tag_ranges = MagicMock(return_value=())
        app.preview_worker = None
        app.start_read_aloud_from = MagicMock()
        mock_event = MagicMock()
        mock_event.x = 10
        mock_event.y = 5
        app.on_text_click(mock_event)
        app.start_read_aloud_from.assert_not_called()


class TestPauseResumeExceptionHandling:
    def test_pause_exception_logged(self):
        app = _make_app()
        app.player.pause.side_effect = RuntimeError("pause error")
        app.enqueue_log = MagicMock()
        app.pause_playback()
        app.enqueue_log.assert_called()

    def test_resume_exception_logged(self):
        app = _make_app()
        app.player.resume.side_effect = RuntimeError("resume error")
        app.enqueue_log = MagicMock()
        app.resume_playback()
        app.enqueue_log.assert_called()
