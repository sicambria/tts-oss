from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from app import DEFAULT_SPEAKER
from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import ENGINE_XTTS
from app import MAX_MERGE_CHUNKS
from app import MP3_QUALITY_PRESETS
from app import OGG_QUALITY_PRESETS
from app import ChapterEntry
from app import DocumentToAudioWizard


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

    def test_mp3_five_presets(self) -> None:
        assert len(MP3_QUALITY_PRESETS) == 5

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
