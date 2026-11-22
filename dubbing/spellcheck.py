"""cyhunspell wrapper — no-op when lib/dicts missing."""
from __future__ import annotations


def available(lang: str = "hu_HU") -> bool:
    try:
        from . import has_cyhunspell
        if not has_cyhunspell():
            return False
        import hunspell
        try:
            hunspell.HunSpell(f"/usr/share/hunspell/{lang}.dic", f"/usr/share/hunspell/{lang}.aff")
            return True
        except Exception:
            # Lib present but dict missing -> report unavailable (UI shows download hint).
            return False
    except Exception:
        return False


def check(lang: str, text: str) -> list[tuple[str, list[str]]]:
    """Return [(word, suggestions)] for misspelled words; [] when unavailable."""
    if not available(lang):
        return []
    try:
        import hunspell
        h = hunspell.HunSpell(f"/usr/share/hunspell/{lang}.dic", f"/usr/share/hunspell/{lang}.aff")
    except Exception:
        return []
    import re
    out: list[tuple[str, list[str]]] = []
    for word in re.findall(r"[\w\u00c0-\u017f']+", text, flags=re.UNICODE):
        try:
            if not h.spell(word):
                try:
                    sug = list(h.suggest(word))[:5]
                except Exception:
                    sug = []
                out.append((word, sug))
        except Exception:
            continue
    return out
