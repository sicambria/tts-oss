from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import ENGINE_AUTO
from app import ENGINE_PIPER
from app import App
from app import LanguagePracticeSession
from app import SynthesisRequest


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Text:
    def __init__(self, content: str):
        self.content = content

    def get(self, *_args):
        return self.content

    def delete(self, *_args):
        self.content = ""

    def insert(self, _index, content):
        self.content = content


def _app(text: str, voices: dict[str, dict[str, str]]) -> App:
    app = App.__new__(App)
    app.text = _Text(text)
    app.piper_voice_options = voices
    app.engine = _Var(ENGINE_PIPER)
    app.piper_voice_label = _Var(next(iter(voices)))
    app.pocket_voice = _Var("lola")
    app.speaker_name = _Var("Ana Florence")
    app.speaker_wav = _Var("")
    app.speed = _Var(1.0)
    app.read_translations = _Var(True)
    app.practice_session = LanguagePracticeSession("es", 1250)
    app.enqueue_log = MagicMock()
    return app


def _base_request() -> SynthesisRequest:
    return SynthesisRequest(
        text="unused",
        language="es",
        output_file=Path("/tmp/practice.mp3"),
        engine=ENGINE_PIPER,
        piper_voice_label="Spanish | Alba | medium",
        piper_voice_code="es_ES-alba-medium",
        speaker_name="Ana Florence",
        speaker_wav="",
        speed=1.0,
    )


@pytest.mark.integration
class TestLanguagePracticeMainFlow:
    def test_handoff_activates_target_language_and_populates_editable_pairs(self):
        app = App.__new__(App)
        app.text = _Text("")
        app.read_translations = _Var(False)
        app.language_display = _Var("Hungarian")
        app.read_translations_check = MagicMock()
        app.export_pairs_button = MagicMock()
        app.root = MagicMock()
        app.clear_read_aloud_highlight = MagicMock()
        app.enqueue_log = MagicMock()

        app.activate_language_practice([("Hola.", "Hello.")], "es", 1000, speak=False)

        assert app.text.content == "Hola.\nHello."
        assert app.practice_session == LanguagePracticeSession("es", 1000)
        assert app.language_display.get() == "Spanish"
        assert app.read_translations.get() is True
        app.root.lift.assert_called_once()

    def test_pairs_become_target_then_english_requests(self):
        app = _app(
            "Hola mundo.\nHello world.\n\nBuenos días.\nGood morning.",
            {
                "Spanish | Alba | medium": {"code": "es_ES-alba-medium", "xtts_language": "es"},
                "English US | Lessac | medium": {"code": "en_US-lessac-medium", "xtts_language": "en"},
            },
        )

        requests = app.practice_requests(_base_request())

        assert [request.language for _item, request in requests] == ["es", "en", "es", "en"]
        assert [request.piper_voice_code for _item, request in requests] == [
            "es_ES-alba-medium",
            "en_US-lessac-medium",
            "es_ES-alba-medium",
            "en_US-lessac-medium",
        ]
        assert [item.pause_after_ms for item, _request in requests] == [300, 1250, 300, 0]

    def test_target_only_mode_omits_english_lines(self):
        app = _app(
            "Olá.\nHello.\n\nTudo bem?\nHow are you?",
            {
                "Portuguese | Tugão | medium": {"code": "pt_PT-tugao-medium", "xtts_language": "pt"},
                "English US | Lessac | medium": {"code": "en_US-lessac-medium", "xtts_language": "en"},
            },
        )
        app.practice_session = LanguagePracticeSession("pt", 800)
        app.read_translations.set(False)

        requests = app.practice_requests(_base_request())

        assert [request.language for _item, request in requests] == ["pt", "pt"]
        assert [item.pause_after_ms for item, _request in requests] == [800, 0]

    def test_missing_english_piper_voice_uses_automatic_english_fallback(self):
        app = _app(
            "Hola.\nHello.",
            {"Spanish | Alba | medium": {"code": "es_ES-alba-medium", "xtts_language": "es"}},
        )

        requests = app.practice_requests(_base_request())

        assert requests[0][1].engine == ENGINE_PIPER
        assert requests[1][1].language == "en"
        assert requests[1][1].engine == ENGINE_AUTO
        app.enqueue_log.assert_called_once()
