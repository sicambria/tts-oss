from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import (
    DEFAULT_PIPER_VOICE_LABEL,
    DEFAULT_SPEAKER,
    ENGINE_AUTO,
    ENGINE_PIPER,
    ENGINE_XTTS,
    MP3_QUALITY_PRESETS,
    OGG_QUALITY_PRESETS,
    MAX_MERGE_CHUNKS,
    DocumentToAudioWizard,
    get_piper_voice_metadata,
)


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
