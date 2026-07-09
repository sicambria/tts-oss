from __future__ import annotations

import pytest

from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import ENGINE_POCKET
from app import ENGINE_XTTS
from app import available_languages
from app import engines_supporting_language
from app import language_code_from_display
from app import language_display_name
from app import piper_language_of_code
from app import piper_languages
from app import piper_voices_for_language
from app import pocket_default_voice
from app import select_engine

# A representative installed-voice map spanning three languages.
VOICES = {
    "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"},
    "English US | Lessac | medium": {"code": "en_US-lessac-medium", "xtts_language": "en"},
    "French | Siwis | low": {"code": "fr_FR-siwis-low", "xtts_language": "fr"},
}


@pytest.mark.unit
class TestPiperLanguageOfCode:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("hu_HU-anna-medium", "hu"),
            ("en_US-lessac-medium", "en"),
            ("en_GB-alan-medium", "en"),
            ("fr_FR-siwis-low", "fr"),
            ("de_DE-thorsten-high", "de"),
        ],
    )
    def test_extracts_iso_language(self, code, expected):
        assert piper_language_of_code(code) == expected


@pytest.mark.unit
class TestPiperLanguages:
    def test_derives_languages_from_installed_voices(self):
        assert piper_languages(VOICES) == {"hu", "en", "fr"}

    def test_empty_options_is_empty(self):
        assert piper_languages({}) == set()


@pytest.mark.unit
class TestPiperVoicesForLanguage:
    def test_filters_by_language(self):
        assert piper_voices_for_language(VOICES, "en") == ["English US | Lessac | medium"]

    def test_no_voices_for_language(self):
        assert piper_voices_for_language(VOICES, "es") == []


@pytest.mark.unit
class TestEnginesSupportingLanguage:
    def test_english_supported_by_all(self):
        engines = engines_supporting_language("en", VOICES)
        assert engines == [ENGINE_PIPER, ENGINE_XTTS, ENGINE_POCKET]

    def test_hungarian_excludes_pocket(self):
        engines = engines_supporting_language("hu", VOICES)
        assert ENGINE_POCKET not in engines
        assert ENGINE_PIPER in engines
        assert ENGINE_XTTS in engines

    def test_language_without_piper_voice_excludes_piper(self):
        # Spanish: no installed Piper voice, but XTTS and Pocket cover it.
        engines = engines_supporting_language("es", VOICES)
        assert engines == [ENGINE_XTTS, ENGINE_POCKET]


@pytest.mark.unit
class TestAvailableLanguages:
    def test_is_union_of_all_engines(self):
        langs = available_languages(VOICES)
        # Every XTTS language plus any Piper-only language shows up.
        for code in ("en", "hu", "fr", "de", "pt", "it", "es"):
            assert code in langs

    def test_ordered_by_display_priority(self):
        langs = available_languages(VOICES)
        assert langs[0] == "en"  # English leads the display order


@pytest.mark.unit
class TestLanguageDisplay:
    def test_display_name_known(self):
        assert language_display_name("hu") == "Hungarian"

    def test_display_name_unknown_uppercases(self):
        assert language_display_name("xx") == "XX"

    def test_round_trip(self):
        for code in ("en", "hu", "fr", "de"):
            assert language_code_from_display(language_display_name(code)) == code


@pytest.mark.unit
class TestXttsLanguageCoverage:
    def test_covers_full_xtts_set(self):
        from app import XTTS_LANGUAGES

        # XTTS v2 speaks 17 languages; the selector must expose all of them.
        assert len(XTTS_LANGUAGES) == 17
        for code in ("en", "hu", "zh-cn", "ja", "ar", "hi", "pl", "ru"):
            assert code in XTTS_LANGUAGES

    def test_every_engine_language_has_a_display_name(self):
        from app import LANGUAGE_NAMES
        from app import POCKET_LANGUAGES
        from app import XTTS_LANGUAGES

        for code in set(XTTS_LANGUAGES) | set(POCKET_LANGUAGES):
            assert code in LANGUAGE_NAMES, f"{code} would render as a raw code"


@pytest.mark.unit
class TestPocketDefaultVoice:
    def test_known_language(self):
        assert pocket_default_voice("fr") == "estelle"

    def test_unknown_language_falls_back(self):
        assert pocket_default_voice("hu") == "alba"


@pytest.mark.unit
class TestSelectEngine:
    def test_explicit_engine_is_honoured(self):
        assert select_engine(ENGINE_XTTS, "en", False, VOICES) == ENGINE_XTTS
        assert select_engine(ENGINE_POCKET, "en", False, VOICES) == ENGINE_POCKET

    def test_auto_without_wav_prefers_piper(self):
        assert select_engine(ENGINE_AUTO, "en", False, VOICES) == ENGINE_PIPER

    def test_auto_with_wav_prefers_xtts(self):
        assert select_engine(ENGINE_AUTO, "en", True, VOICES) == ENGINE_XTTS

    def test_auto_skips_piper_when_no_voice_for_language(self):
        # Spanish has no Piper voice installed → Auto must not resolve to Piper.
        assert select_engine(ENGINE_AUTO, "es", False, VOICES) == ENGINE_XTTS

    def test_auto_falls_back_to_only_supported_engine(self):
        # Portuguese with a reference wav but no Piper voice → XTTS (supports cloning).
        assert select_engine(ENGINE_AUTO, "pt", True, VOICES) == ENGINE_XTTS
