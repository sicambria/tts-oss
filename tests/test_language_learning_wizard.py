from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import CEFR_PRESETS
from app import ENGINE_PIPER
from app import ENGINE_POCKET
from app import LanguageLearningAvailability
from app import LanguageLearningWizard
from app import LanguageSessionConfig
from app import SessionState


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class TextBox:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def configure(self, **_kwargs):
        pass


def wizard() -> LanguageLearningWizard:
    instance = LanguageLearningWizard.__new__(LanguageLearningWizard)
    instance.app = MagicMock()
    instance.app.piper_voice_options = {
        "Portuguese | Tugão | medium": {"code": "pt_PT-tugao-medium"},
        "English US | Lessac | medium": {"code": "en_US-lessac-medium"},
    }
    instance.availability = LanguageLearningAvailability(True, "Ready", Path("/wordlists"))
    instance.settings = {}
    instance.window = MagicMock()
    instance.status_var = Var("Ready")
    instance.preset_var = Var("A2")
    instance.lang_var = Var("Portuguese")
    instance.level_var = Var(1)
    instance.count_var = Var(2)
    instance.max_length_var = Var(80)
    instance.plural_chance_var = Var(0.3)
    instance.seed_var = Var("")
    instance.top_n_var = Var("")
    instance.base_word_var = Var("")
    instance.base_word_count_var = Var(10)
    instance.base_template_var = Var("")
    instance.vary_role_var = Var("")
    instance.vary_words_var = Var("")
    instance.pair_pause_var = Var(1200)
    instance.repeat_target_sentence_var = Var(True)
    instance.piper_voice_label_var = Var("Portuguese | Tugão | medium")
    instance.pocket_voice_var = Var("alba")
    instance.speaker_name_var = Var("Speaker")
    instance.speaker_wav_var = Var("")
    instance.engine_var = Var(ENGINE_PIPER)
    instance.speed_var = Var(1.1)
    instance.generate_button = MagicMock()
    instance.speak_button = MagicMock()
    instance.output_text = TextBox()
    instance.generated_pairs = []
    instance.session_state = SessionState.IDLE
    instance._job_id = 0
    instance.worker = None
    import threading

    instance.stop_event = threading.Event()
    instance.pause_event = threading.Event()
    instance.pause_event.set()
    instance._temp_files = []
    return instance


@pytest.mark.unit
class TestLanguageLearningWizardSettings:
    def test_validate_language_normalizes_unknown_display(self):
        instance = wizard()
        instance.lang_var.set("Klingon")

        assert instance._validate_language() is True
        assert instance.lang_var.get() == "Portuguese"
        assert "not supported" in instance.status_var.get()

    def test_apply_preset_updates_controls_and_saved_defaults(self):
        instance = wizard()
        instance.preset_var.set("B2")

        instance._apply_preset()

        assert instance.level_var.get() == CEFR_PRESETS["B2"]["level"]
        assert instance.count_var.get() == CEFR_PRESETS["B2"]["count"]
        assert instance.settings == CEFR_PRESETS["B2"]

    def test_collect_settings_converts_optional_fields(self):
        instance = wizard()
        instance.seed_var.set("42")
        instance.top_n_var.set("500")
        instance.base_word_var.set(" casa ")
        instance.base_template_var.set("tpl-1")
        instance.vary_role_var.set("N_SUBJ")
        instance.vary_words_var.set("casa, carro")

        assert instance._collect_settings() == {
            "preset": "A2",
            "language": "pt",
            "level": 1,
            "count": 2,
            "max_length": 80,
            "plural_chance": 0.3,
            "seed": 42,
            "top_n": 500,
            "base_word": "casa",
            "base_word_count": 10,
            "base_template": "tpl-1",
            "vary_role": "N_SUBJ",
            "vary_words": "casa, carro",
            "pair_pause_ms": 1200,
            "repeat_target_sentence": True,
        }

    def test_language_change_refreshes_templates_and_clears_unknown_template(self):
        instance = wizard()
        instance.template_box = MagicMock()
        instance.base_template_var.set("stale")
        instance._get_template_ids = MagicMock(return_value=["fresh"])

        instance._on_language_changed()

        instance.template_box.configure.assert_called_once_with(values=["fresh"])
        assert instance.base_template_var.get() == ""

    def test_save_preset_updates_app_and_persists(self):
        instance = wizard()
        instance.app.settings = {}
        with patch("app.save_app_settings") as save:
            instance._save_preset()

        assert instance.app.settings["language_learning"]["language"] == "pt"
        save.assert_called_once_with(instance.app.settings)
        instance.window.after.assert_called_once()


@pytest.mark.unit
class TestLanguageLearningWizardGeneration:
    def test_generation_options_preserve_empty_optional_strings(self):
        instance = wizard()
        assert instance._generation_options()["seed"] is None
        assert instance._generation_options()["base_word"] == ""

    def test_generate_pairs_normal_mode_formats_translations(self, monkeypatch):
        instance = wizard()
        calls = []

        class Generator:
            def __init__(self, words, **kwargs):
                calls.append((words, kwargs))

            def generate(self, count):
                assert count == 2
                return [type("Sentence", (), {"words": ["Olá", "mundo"]})()]

        generator = ModuleType("language_practice.generator")
        generator.Generator = Generator
        language = ModuleType("language_practice.languages.pt")
        language.parse_wordlist = lambda path: ["raw"]
        language.enrich_words = lambda raw: ["word"]
        language.build_en_dict = lambda words: {"word": "word"}
        language.translate = lambda words, dictionary: "Hello world"
        monkeypatch.setitem(sys.modules, "language_practice.generator", generator)
        monkeypatch.setitem(sys.modules, "language_practice.languages.pt", language)

        assert instance._generate_pairs(instance._generation_options()) == [("Olá mundo", "Hello world")]
        assert calls[0][1]["lang"] is language

    def test_generate_pairs_base_word_mode_matches_accents(self, monkeypatch):
        instance = wizard()
        instance.base_word_var.set("cafe")
        word = type("Word", (), {"pt": "café"})()

        class Generator:
            def __init__(self, *_args, **_kwargs):
                pass

            def generate_with_base_word(self, count, base, seed):
                assert (count, base, seed) == (10, word, None)
                return [type("Sentence", (), {"words": ["café"]})()]

        generator = ModuleType("language_practice.generator")
        generator.Generator = Generator
        language = ModuleType("language_practice.languages.pt")
        language.parse_wordlist = lambda path: [word]
        language.enrich_words = lambda words: words
        language.build_en_dict = lambda words: {}
        language.translate = lambda words, dictionary: "coffee"
        monkeypatch.setitem(sys.modules, "language_practice.generator", generator)
        monkeypatch.setitem(sys.modules, "language_practice.languages.pt", language)

        assert instance._generate_pairs(instance._generation_options()) == [("café", "coffee")]

    def test_generate_pairs_batch_mode_rejects_unknown_template(self, monkeypatch):
        instance = wizard()
        instance.base_template_var.set("missing")
        generator = ModuleType("language_practice.generator")
        generator.Generator = lambda *_args, **_kwargs: MagicMock()
        language = ModuleType("language_practice.languages.pt")
        language.parse_wordlist = lambda path: []
        language.enrich_words = lambda words: words
        language.build_en_dict = lambda words: {}
        language.TEMPLATES = []
        monkeypatch.setitem(sys.modules, "language_practice.generator", generator)
        monkeypatch.setitem(sys.modules, "language_practice.languages.pt", language)

        with pytest.raises(ValueError, match="Template 'missing'"):
            instance._generate_pairs(instance._generation_options())

    def test_handoff_ignores_stale_job_and_persists_current_job(self):
        instance = wizard()
        instance.app.settings = {}
        instance._job_id = 3
        instance._handoff_pairs([("Olá", "Hello")], 2, False)
        instance.app.activate_language_practice.assert_not_called()

        with patch("app.save_app_settings") as save:
            instance._handoff_pairs([("Olá", "Hello")], 3, True)
        instance.app.activate_language_practice.assert_called_once()
        assert instance.app.activate_language_practice.call_args.kwargs["speak"] is True
        save.assert_called_once()
        instance.window.destroy.assert_called_once()


@pytest.mark.integration
class TestLanguageLearningWizardPlaybackAndExport:
    def test_build_request_uses_matching_piper_voice(self):
        instance = wizard()
        config = LanguageSessionConfig("pt", ENGINE_PIPER, 1.25, 1000, True, True)

        request = instance._build_request("Olá", config=config)

        assert request.language == "pt"
        assert request.piper_voice_code == "pt_PT-tugao-medium"
        assert request.speed == 1.25

    def test_build_request_uses_language_default_pocket_voice_for_translation(self):
        instance = wizard()
        config = LanguageSessionConfig("pt", ENGINE_POCKET, 1.0, 1000, True, False)

        request = instance._build_request("Hello", "en", config)

        assert request.language == "en"
        assert request.speaker_name

    def test_pairs_from_output_reads_editable_blocks_and_retains_fallback(self):
        instance = wizard()
        instance.generated_pairs = [("old", "old translation")]
        instance.output_text.value = "1. Olá\nHello\n\n2. Tudo bem?\n"

        assert instance._pairs_from_output() == [("Olá", "Hello"), ("Tudo bem?", "")]
        instance.output_text.value = ""
        assert instance._pairs_from_output() == [("Olá", "Hello"), ("Tudo bem?", "")]

    def test_session_pause_resume_and_stop_control_player(self):
        instance = wizard()
        instance.session_state = SessionState.PLAYING
        instance._toggle_pause()
        assert instance.session_state == SessionState.PAUSED
        instance.app.player.pause.assert_called_once()

        instance._toggle_pause()
        assert instance.session_state == SessionState.PLAYING
        instance.app.player.resume.assert_called_once()

        instance._stop_session()
        assert instance.stop_event.is_set()
        instance.app.player.stop.assert_called_once_with(quiet=True)

    def test_cleanup_temp_file_removes_disk_file_and_tracking(self, temp_dir):
        instance = wizard()
        path = temp_dir / "temp.wav"
        path.write_bytes(b"audio")
        instance._temp_files = [path]

        instance._cleanup_temp_file(path)

        assert not path.exists()
        assert instance._temp_files == []

    @pytest.mark.parametrize(
        ("fmt", "suffix", "expected"),
        [
            ("Text", ".txt", "Olá\nHello"),
            ("Anki CSV", ".csv", '"Olá","Hello","language-learning"'),
            ("JSON", ".json", None),
        ],
    )
    def test_export_writes_selected_format(self, temp_dir, fmt, suffix, expected):
        instance = wizard()
        instance.generated_pairs = [("Olá", "Hello")]
        instance.show_trans_var = Var(True)
        path = temp_dir / f"pairs{suffix}"
        with patch("app.filedialog.asksaveasfilename", return_value=str(path)):
            instance._do_export(fmt)

        assert path.exists()
        if expected:
            assert expected in path.read_text(encoding="utf-8")
        else:
            assert json.loads(path.read_text(encoding="utf-8"))[0]["front"] == "Olá"

    def test_clear_and_close_save_settings_and_destroy(self):
        instance = wizard()
        instance.output_text.value = "generated"
        instance.generated_pairs = [("Olá", "Hello")]
        instance._clear()
        assert instance.generated_pairs == []
        assert instance.status_var.get() == "Cleared"

        instance.app.settings = {}
        with patch("app.save_app_settings") as save:
            instance._on_close()
        assert instance.app.settings["language_learning"]["language"] == "pt"
        save.assert_called_once()
        instance.window.destroy.assert_called_once()
