from __future__ import annotations

import pytest

from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import LanguageLearningWizard
from app import LanguageSessionConfig


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _App:
    piper_voice_options = {
        "English US | Lessac | medium": {"code": "en_US-lessac-medium", "xtts_language": "en"},
        "Hungarian | Anna | medium": {"code": "hu_HU-anna-medium", "xtts_language": "hu"},
    }


class _WizardRequestHarness:
    def __init__(self, engine: str):
        self.app = _App()
        self.engine_var = _Var(engine)
        self.lang_var = _Var("Portuguese")
        self.piper_voice_label_var = _Var("Hungarian | Anna | medium")
        self.pocket_voice_var = _Var("rafael")
        self.speaker_name_var = _Var("Ana Florence")
        self.speaker_wav_var = _Var("")
        self.speed_var = _Var(1.0)


def test_translation_request_uses_english_and_an_english_piper_voice_when_auto():
    wizard = _WizardRequestHarness(ENGINE_AUTO)
    config = LanguageSessionConfig("pt", ENGINE_AUTO, 1.0, 0, True)

    request = LanguageLearningWizard._build_request(wizard, "A translation", "en", config)

    assert request.language == "en"
    assert request.piper_voice_code == "en_US-lessac-medium"


def test_explicit_piper_requires_a_voice_for_the_requested_learning_language():
    wizard = _WizardRequestHarness(ENGINE_PIPER)
    config = LanguageSessionConfig("pt", ENGINE_PIPER, 1.0, 0, True)

    with pytest.raises(RuntimeError, match="no installed Portuguese voice"):
        LanguageLearningWizard._build_request(wizard, "Olá", "pt", config)
