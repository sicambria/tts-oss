from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import DEFAULT_SPEAKER
from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import ENGINE_POCKET
from app import ENGINE_XTTS
from app import MAX_MERGE_CHUNKS
from app import MP3_QUALITY_PRESETS
from app import OGG_QUALITY_PRESETS
from app import ChapterEntry
from app import DocumentConversionRun
from app import DocumentToAudioWizard
from app import sentence_synthesis_units


class _MockVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value

    def trace_add(self, *_args: object) -> None:
        pass


class _MockBoolVar:
    def __init__(self, value: bool = False) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = value


class _MockDoubleVar:
    def __init__(self, value: float = 1.0) -> None:
        self._value = value

    def get(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = value

    def trace_add(self, *_args: object) -> None:
        pass


class MockApp:
    def __init__(self) -> None:
        self.language = _MockVar("hu")
        self.engine = _MockVar(ENGINE_AUTO)
        self.piper_voice_label = _MockVar("Hungarian | Anna | medium")
        self.piper_voice_options = {
            "Hungarian | Anna | medium": {
                "code": "hu_HU-anna-medium",
                "xtts_language": "hu",
            },
            "English US | Lessac | medium": {
                "code": "en_US-lessac-medium",
                "xtts_language": "en",
            },
        }
        self.speed = _MockDoubleVar(1.0)
        self.speaker_name = _MockVar(DEFAULT_SPEAKER)
        self.speaker_wav = _MockVar("")
        self.service = MagicMock()
        self.enqueue_log = MagicMock()
        self.root = MagicMock()


def _make_wizard(app: MockApp) -> DocumentToAudioWizard:
    mock_toplevel = MagicMock()
    with patch("app.Toplevel", return_value=mock_toplevel):
        with patch("app.StringVar", new=_MockVar):
            with patch("app.BooleanVar", new=_MockBoolVar):
                with patch("app.DoubleVar", new=_MockDoubleVar):
                    with patch.object(DocumentToAudioWizard, "_build_ui", return_value=None):
                        wizard = DocumentToAudioWizard(app)
                        wizard.window = mock_toplevel
                        wizard.tree = MagicMock()
                        wizard.overall_bar = MagicMock()
                        wizard.file_bar = MagicMock()
                        wizard.start_button = MagicMock()
                        wizard.quality_box = MagicMock()
                        return wizard


class TestBuildRequest:
    def test_piper_engine_settings(self) -> None:
        app = MockApp()
        app.engine.set(ENGINE_PIPER)
        wizard = _make_wizard(app)

        req = wizard._build_request("test text", Path("/tmp/out.mp3"))
        assert req.text == "test text"
        assert req.engine == ENGINE_PIPER
        assert req.language == "hu"
        assert req.piper_voice_code == "hu_HU-anna-medium"
        assert req.piper_voice_label == "Hungarian | Anna | medium"

    def test_xtts_with_speaker_wav(self) -> None:
        app = MockApp()
        app.engine.set(ENGINE_XTTS)
        app.speaker_wav.set("/path/to/voice.wav")
        wizard = _make_wizard(app)

        req = wizard._build_request("test text", Path("/tmp/out.ogg"))
        assert req.engine == ENGINE_XTTS
        assert req.speaker_wav == "/path/to/voice.wav"

    def test_default_language_fallback(self) -> None:
        app = MockApp()
        app.language.set("")
        wizard = _make_wizard(app)

        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.language == "hu"

    def test_missing_voice_label_fallback(self) -> None:
        app = MockApp()
        app.piper_voice_label.set("nonexistent")
        wizard = _make_wizard(app)

        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.piper_voice_code == "hu_HU-anna-medium"

    def test_output_file_set_correctly(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)

        out = Path("/tmp/output.mp3")
        req = wizard._build_request("text", out)
        assert req.output_file == out

    def test_empty_speaker_wav_passed_through(self) -> None:
        app = MockApp()
        app.speaker_wav.set("")
        wizard = _make_wizard(app)

        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.speaker_wav == ""

    def test_explicit_auto_engine(self) -> None:
        app = MockApp()
        app.engine.set(ENGINE_AUTO)
        wizard = _make_wizard(app)

        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.engine == ENGINE_AUTO

    def test_pocket_engine_settings(self) -> None:
        app = MockApp()
        app.language.set("en")  # Pocket supports English (not Hungarian)
        app.engine.set(ENGINE_POCKET)
        wizard = _make_wizard(app)

        req = wizard._build_request("test text", Path("/tmp/out.mp3"))
        assert req.engine == ENGINE_POCKET
        # Pocket's voice comes from its own dropdown; "alba" is the English default.
        assert req.speaker_name == "alba"


class TestQualityPresets:
    def test_mp3_all_presets_have_bitrate(self) -> None:
        for label, preset in MP3_QUALITY_PRESETS.items():
            assert "bitrate" in preset, f"MP3 preset '{label}' missing bitrate"
            assert isinstance(preset["bitrate"], str)
            assert preset["bitrate"].endswith("k")

    def test_ogg_all_presets_have_quality_params(self) -> None:
        for label, preset in OGG_QUALITY_PRESETS.items():
            assert "quality_params" in preset, f"OGG preset '{label}' missing quality_params"
            params = preset["quality_params"]
            assert isinstance(params, list)
            assert "-q:a" in params

    def test_mp3_includes_low_bitrate_presets(self) -> None:
        assert {"8 kbps (smallest)", "16 kbps", "24 kbps", "32 kbps", "64 kbps"} <= set(MP3_QUALITY_PRESETS)

    def test_ogg_five_presets(self) -> None:
        assert len(OGG_QUALITY_PRESETS) == 5

    def test_max_merge_chunks_value(self) -> None:
        assert MAX_MERGE_CHUNKS == 500

    def test_wizard_class_refs_presets(self) -> None:
        assert DocumentToAudioWizard.MP3_PRESETS is MP3_QUALITY_PRESETS
        assert DocumentToAudioWizard.OGG_PRESETS is OGG_QUALITY_PRESETS
        assert DocumentToAudioWizard.MAX_MERGE_CHUNKS == 500


class TestDocListManipulation:
    def test_add_documents_dedup(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._refresh_tree = MagicMock()

        with patch(
            "app.filedialog.askopenfilenames",
            return_value=["/a/doc.docx", "/b/doc.pdf", "/a/doc.docx"],
        ):
            wizard._add_documents()

        assert len(wizard.documents) == 2
        assert wizard.documents[0] == Path("/a/doc.docx")
        assert wizard.documents[1] == Path("/b/doc.pdf")

    def test_remove_selected(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._refresh_tree = MagicMock()
        wizard.documents = [
            Path("/a/doc.docx"),
            Path("/b/doc.pdf"),
            Path("/c/doc.odt"),
        ]
        wizard.doc_status = {p: "Ready" for p in wizard.documents}
        wizard.tree.selection.return_value = [
            str(Path("/a/doc.docx")),
            str(Path("/c/doc.odt")),
        ]

        wizard._remove_selected()

        assert len(wizard.documents) == 1
        assert wizard.documents[0] == Path("/b/doc.pdf")
        assert Path("/a/doc.docx") not in wizard.doc_status

    def test_clear_all(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._refresh_tree = MagicMock()
        wizard.documents = [Path("/a/doc.docx")]
        wizard.doc_status = {Path("/a/doc.docx"): "Ready"}

        wizard._clear_all()

        assert wizard.documents == []
        assert wizard.doc_status == {}


class TestFormatChange:
    def test_format_changed_to_ogg_swaps_presets(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("OGG")
        wizard._on_format_changed()

        assert wizard.quality_preset.get() in OGG_QUALITY_PRESETS
        wizard.quality_box.configure.assert_called()

    def test_format_changed_to_mp3_swaps_presets(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("MP3")
        wizard._on_format_changed()

        assert wizard.quality_preset.get() in MP3_QUALITY_PRESETS
        wizard.quality_box.configure.assert_called()

    def test_format_changed_to_wav_disables_quality(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("WAV")
        wizard._on_format_changed()

        assert wizard.quality_preset.get() == "Lossless (no quality setting)"
        wizard.quality_box.configure.assert_called_with(
            values=["Lossless (no quality setting)"], state="disabled"
        )


class TestBuildRequestEdgeCases:
    def test_empty_language_fallback(self) -> None:
        app = MockApp()
        app.language.set("")
        wizard = _make_wizard(app)
        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.language == "hu"

    def test_missing_piper_voice_options_key(self) -> None:
        app = MockApp()
        app.piper_voice_label.set("French | Test | high")
        wizard = _make_wizard(app)
        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.piper_voice_code == "hu_HU-anna-medium"

    def test_empty_piper_voice_label_uses_default(self) -> None:
        app = MockApp()
        app.piper_voice_label.set("")
        wizard = _make_wizard(app)
        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.piper_voice_code == "hu_HU-anna-medium"


class TestBuildQualityParams:
    def test_mp3_preset(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("MP3")
        wizard.quality_preset.set("320 kbps")
        preset = wizard.MP3_PRESETS.get("320 kbps", {})
        assert preset["bitrate"] == "320k"

    def test_ogg_preset(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("OGG")
        wizard.quality_preset.set("High (q5)")
        preset = wizard.OGG_PRESETS.get("High (q5)", {})
        assert preset["quality_params"] == ["-q:a", "5"]

    def test_wav_no_preset(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.output_format.set("WAV")
        preset = wizard.MP3_PRESETS.get("WAV", {}) if wizard.output_format.get() == "MP3" else {}
        assert preset == {}


class TestDoExtraction:
    def test_extraction_status_updates(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._update_doc_status = MagicMock()
        wizard._set_overall = MagicMock()
        wizard.documents = [Path("/tmp/test.docx")]
        wizard.extracted_texts = {}
        wizard._chapter_entries = {}
        wizard.split_chapters.set(False)
        wizard.pause_event.set()
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()

        with patch("app.DocumentExtractor.extract_text", return_value="Hello world."):
            wizard._do_extraction()

        assert len(wizard.extracted_texts) == 1
        entry = list(wizard.extracted_texts.keys())[0]
        assert isinstance(entry, ChapterEntry)
        assert wizard.extracted_texts[entry] == "Hello world."

    def test_worker_uses_captured_page_range(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._update_doc_status = MagicMock()
        wizard._set_overall = MagicMock()
        wizard.documents = [Path("/tmp/test.pdf")]
        wizard.extracted_texts = {}
        wizard._chapter_entries = {}
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()
        run = DocumentConversionRun(
            documents=(Path("/tmp/test.pdf"),), output_folder=Path("/tmp/out"), from_page=61, to_page=70,
            merge_files=False, split_chapters=False, chapter_level="all", output_format="MP3", quality_preset="64 kbps",
            piper_voice_label="Hungarian | Anna | medium", language="hu", engine=ENGINE_AUTO,
            speaker_name=DEFAULT_SPEAKER, pocket_voice="alba", speaker_wav="", speed=1.0,
        )

        with patch("app.DocumentExtractor.extract_text", return_value="Selected pages only.") as extract:
            wizard._do_extraction(run)

        extract.assert_called_once_with(Path("/tmp/test.pdf"), from_page=61, to_page=70)


class TestDoPreparation:
    def test_chunk_counting(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard._set_overall = MagicMock()
        wizard.documents = [Path("/tmp/test.docx")]
        entry = ChapterEntry(
            source_path=Path("/tmp/test.docx"),
            index=0,
            title="",
            content="Word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
            word_count=10,
        )
        wizard.extracted_texts = {entry: entry.content}
        wizard.chunk_counts = {}
        wizard.pause_event.set()
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()

        wizard._do_preparation()

        assert entry in wizard.chunk_counts
        assert wizard.chunk_counts[entry] >= 1

    def test_repetition_counts_sentence_units_individually(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.repeat_sentences.set(True)
        wizard._set_overall = MagicMock()
        entry = ChapterEntry(
            source_path=Path("/tmp/test.docx"),
            index=0,
            title="",
            content="First sentence. Second sentence.",
            word_count=4,
        )
        wizard.extracted_texts = {entry: entry.content}
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()

        wizard._do_preparation()

        assert sentence_synthesis_units(entry.content) == ["First sentence.", "Second sentence."]
        assert wizard.chunk_counts[entry] == 2


class TestRefreshTree:
    def test_rows_inserted(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.documents = [Path("/tmp/test.docx")]
        wizard.doc_status = {Path("/tmp/test.docx"): "Ready"}
        wizard.start_button = MagicMock()
        wizard.tree.get_children.return_value = []
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat", return_value=MagicMock(st_size=1024)):
                wizard._refresh_tree()
        wizard.tree.insert.assert_called_once()


class TestParsePageRange:
    def test_both_empty_returns_none(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.from_page.set("")
        wizard.to_page.set("")
        from_page, to_page = wizard._parse_page_range()
        assert from_page is None
        assert to_page is None

    def test_both_populated(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.from_page.set("3")
        wizard.to_page.set("7")
        from_page, to_page = wizard._parse_page_range()
        assert from_page == 3
        assert to_page == 7

    def test_only_from(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.from_page.set("5")
        wizard.to_page.set("")
        from_page, to_page = wizard._parse_page_range()
        assert from_page == 5
        assert to_page is None

    def test_only_to(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.from_page.set("")
        wizard.to_page.set("10")
        from_page, to_page = wizard._parse_page_range()
        assert from_page is None
        assert to_page == 10

    @pytest.mark.parametrize(
        ("from_value", "to_value", "message"),
        [
            ("one", "", "From page must be a whole number"),
            ("0", "", "From page must be at least 1"),
            ("", "-1", "To page must be a whole number"),
            ("7", "3", "From page must not exceed To page"),
        ],
    )
    def test_invalid_page_range_is_rejected(self, from_value, to_value, message) -> None:
        wizard = _make_wizard(MockApp())
        wizard.from_page.set(from_value)
        wizard.to_page.set(to_value)

        with pytest.raises(ValueError, match=message):
            wizard._parse_page_range()

    def test_invalid_page_range_shows_immediate_feedback(self) -> None:
        wizard = _make_wizard(MockApp())
        wizard.documents = [Path("/tmp/test.pdf")]
        wizard.from_page_entry = MagicMock()
        wizard.to_page_entry = MagicMock()
        wizard.from_page.set("7")
        wizard.to_page.set("3")

        wizard._on_page_range_changed()

        assert wizard.page_range_error.get() == "From page must not exceed To page."
        wizard.from_page_entry.configure.assert_called_with(style="Invalid.TEntry")
        wizard.to_page_entry.configure.assert_called_with(style="Invalid.TEntry")
        wizard.start_button.configure.assert_called_with(state="disabled")

    def test_valid_page_range_clears_feedback_and_enables_start(self) -> None:
        wizard = _make_wizard(MockApp())
        wizard.documents = [Path("/tmp/test.pdf")]
        wizard.from_page_entry = MagicMock()
        wizard.to_page_entry = MagicMock()
        wizard.from_page.set("2")
        wizard.to_page.set("3")

        wizard._on_page_range_changed()

        assert wizard.page_range_error.get() == ""
        wizard.from_page_entry.configure.assert_called_with(style="TEntry")
        wizard.to_page_entry.configure.assert_called_with(style="TEntry")
        wizard.start_button.configure.assert_called_with(state="normal")


class TestWizardBuildRequestSpeed:
    def test_speed_included(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.speed == 1.0

    def test_custom_speed_included(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.wizard_speed.set(1.7)
        req = wizard._build_request("text", Path("/tmp/out.mp3"))
        assert req.speed == 1.7


class TestDocumentSynthesisAssembly:
    def test_appends_each_yielded_segment_once(self) -> None:
        class RecordingAudio:
            def __init__(self) -> None:
                self.parts: list[object] = []

            def __iadd__(self, other: object):
                self.parts.append(other)
                return self

        app = MockApp()
        wizard = _make_wizard(app)
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.pause_event = MagicMock()
        wizard._total_chunks = 2
        wizard.phase_text = MagicMock()
        wizard.quality_preset = _MockVar("Standard")
        wizard.output_format = _MockVar("MP3")
        wizard._build_request = MagicMock()
        first_segment = object()
        second_segment = object()
        pause = object()
        combined = RecordingAudio()
        app.service.iter_segments.return_value = [(MagicMock(), first_segment), (MagicMock(), second_segment)]

        with patch("app.export_audio_segment"):
            with patch("app.AudioSegment.silent", side_effect=lambda duration: combined if duration == 0 else pause):
                wizard._synthesize_text(
                    "Sentence one. Sentence two.",
                    Path("/tmp/out.mp3"),
                    expected_chunks=2,
                    doc_index=0,
                    total_docs=1,
                    cumul_chunks_start=0,
                )

        assert combined.parts == [first_segment, pause, second_segment]

    def test_repetition_duplicates_each_sentence_audio(self) -> None:
        class RecordingAudio:
            def __init__(self) -> None:
                self.parts: list[object] = []

            def __iadd__(self, other: object):
                self.parts.append(other)
                return self

        app = MockApp()
        wizard = _make_wizard(app)
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.pause_event = MagicMock()
        wizard._total_chunks = 2
        wizard.phase_text = MagicMock()
        wizard.quality_preset = _MockVar("Standard")
        wizard.output_format = _MockVar("MP3")
        first_segment = object()
        second_segment = object()
        pause = object()
        combined = RecordingAudio()
        wizard._build_request = lambda text, _output, _run: MagicMock(text=text)
        app.service.iter_segments.side_effect = lambda request: [
            (MagicMock(), first_segment if request.text.startswith("Sentence one") else second_segment)
        ]
        run = DocumentConversionRun(
            documents=(), output_folder=Path("/tmp/out"), from_page=None, to_page=None,
            merge_files=False, split_chapters=False, chapter_level="all", output_format="MP3",
            quality_preset="Standard", piper_voice_label="Hungarian | Anna | medium", language="hu",
            engine=ENGINE_AUTO, speaker_name=DEFAULT_SPEAKER, pocket_voice="alba", speaker_wav="", speed=1.0,
            repeat_sentences=True,
        )

        with patch("app.export_audio_segment"):
            with patch("app.AudioSegment.silent", side_effect=lambda duration: combined if duration == 0 else pause):
                wizard._synthesize_text(
                    "Sentence one. Sentence two.", Path("/tmp/out.mp3"), expected_chunks=2,
                    doc_index=0, total_docs=1, cumul_chunks_start=0, run=run,
                )

        assert combined.parts == [first_segment, pause, first_segment, pause, second_segment, pause, second_segment]


class TestDoSynthesisPerFile:
    def test_single_entry_synthesizes_and_finishes(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        entry = ChapterEntry(
            source_path=Path("/tmp/test.docx"),
            index=0,
            title="",
            content="Hello world.",
            word_count=2,
        )
        wizard.extracted_texts = {entry: "Hello world."}
        wizard._chapter_entries = {}
        wizard.chunk_counts = {entry: 1}
        wizard._total_chunks = 1
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()
        wizard._update_doc_status = MagicMock()
        wizard._set_overall = MagicMock()
        wizard._set_file = MagicMock()
        wizard._finish = MagicMock()
        wizard._synthesize_text = MagicMock()
        wizard._chapter_output_path = MagicMock(return_value=Path("/tmp/out/test.mp3"))
        wizard.phase_text = MagicMock()

        output_folder = Path("/tmp/out")
        wizard._do_synthesis_per_file(output_folder)

        wizard._synthesize_text.assert_called_once()
        wizard._finish.assert_called_once_with(None)

    def test_stop_event_breaks_early(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        entry = ChapterEntry(
            source_path=Path("/tmp/test.docx"),
            index=0,
            title="",
            content="Hello world.",
            word_count=2,
        )
        wizard.extracted_texts = {entry: "Hello world."}
        wizard.chunk_counts = {entry: 1}
        wizard._total_chunks = 1
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = True
        wizard.window.after = MagicMock()
        wizard._update_doc_status = MagicMock()
        wizard._finish = MagicMock()
        wizard._synthesize_text = MagicMock()

        output_folder = Path("/tmp/out")
        wizard._do_synthesis_per_file(output_folder)

        wizard._synthesize_text.assert_not_called()


class TestDoSynthesisMerged:
    def test_merges_text_and_synthesizes(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        entry1 = ChapterEntry(
            source_path=Path("/tmp/a.docx"),
            index=0,
            title="Chapter 1",
            content="Content one.",
            word_count=2,
        )
        entry2 = ChapterEntry(
            source_path=Path("/tmp/b.docx"),
            index=0,
            title="",
            content="Content two.",
            word_count=2,
        )
        wizard.extracted_texts = {entry1: "Content one.", entry2: "Content two."}
        wizard.chunk_counts = {entry1: 1, entry2: 1}
        wizard._total_chunks = 2
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()
        wizard._finish = MagicMock()
        wizard._synthesize_text = MagicMock()
        wizard.phase_text = MagicMock()

        output_folder = Path("/tmp/out")
        with patch("time.strftime", return_value="20240101_120000"):
            wizard._do_synthesis_merged(output_folder)

        wizard._synthesize_text.assert_called_once()
        call_args = wizard._synthesize_text.call_args
        assert "Chapter 1" in call_args[0][0]
        assert "Content one" in call_args[0][0]
        assert "Content two" in call_args[0][0]
        assert call_args[0][1] == output_folder / "merged_20240101_120000.mp3"

    def test_no_entries_raises(self) -> None:
        app = MockApp()
        wizard = _make_wizard(app)
        wizard.extracted_texts = {}
        wizard.stop_event = MagicMock()
        wizard.stop_event.is_set.return_value = False
        wizard.window.after = MagicMock()
        wizard._finish = MagicMock()

        output_folder = Path("/tmp/out")
        with pytest.raises(RuntimeError, match="No documents"):
            wizard._do_synthesis_merged(output_folder)
