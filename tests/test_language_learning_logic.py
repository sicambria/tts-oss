from __future__ import annotations

from app import language_practice_pairs


def test_language_practice_pairs_keep_editable_target_and_english_lines():
    pairs = language_practice_pairs("Olá.\nHello.\n\nTudo bem?\nHow are you?")

    assert pairs == [("Olá.", "Hello."), ("Tudo bem?", "How are you?")]


def test_language_practice_pairs_allow_target_only_edits():
    assert language_practice_pairs("Hola.") == [("Hola.", "")]
