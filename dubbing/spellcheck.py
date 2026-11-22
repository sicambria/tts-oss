"""Hungarian spellcheck — pure-Python spylls backend (wheel, no sudo, no build).

Backend chain: spylls (primary) -> cyhunspell (legacy, if already installed).
Dictionaries are read from the system (world-readable, no sudo to read):
/usr/share/hunspell is standard on Debian/Ubuntu/Fedora (hunspell-hu).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DICT_SEARCH_DIRS = (
    Path("/usr/share/hunspell"),
    Path("/usr/local/share/hunspell"),
    Path("/usr/share/myspell"),
)

_BACKEND: str | None = None


def _spylls_available() -> bool:
    try:
        import spylls  # noqa: F401
        return True
    except Exception:
        return False


def _cyhunspell_available() -> bool:
    try:
        import hunspell  # noqa: F401  # cyhunspell installs as hunspell
        return True
    except Exception:
        try:
            import cyhunspell  # noqa: F401
            return True
        except Exception:
            return False


def backend() -> str | None:
    """Return 'spylls', 'cyhunspell', or None. Cached per process."""
    global _BACKEND
    if _BACKEND is None:
        if _spylls_available():
            _BACKEND = "spylls"
        elif _cyhunspell_available():
            _BACKEND = "cyhunspell"
        else:
            _BACKEND = ""
    return _BACKEND or None


def find_dictionary(lang: str = "hu_HU") -> tuple[Path, Path] | None:
    """Locate (dic, aff) for lang. Returns None when not installed."""
    for directory in DICT_SEARCH_DIRS:
        dic = directory / f"{lang}.dic"
        aff = directory / f"{lang}.aff"
        if dic.is_file() and aff.is_file():
            return dic, aff
    try:
        from . import spellcheck as _  # noqa: F401  # keep package importable in tests
    except Exception:
        pass
    return None


def available(lang: str = "hu_HU") -> bool:
    if backend() == "spylls":
        return find_dictionary(lang) is not None
    if backend() == "cyhunspell":
        try:
            import hunspell
            hunspell.HunSpell(f"/usr/share/hunspell/{lang}.dic", f"/usr/share/hunspell/{lang}.aff")
            return True
        except Exception:
            return False
    return False


@lru_cache(maxsize=4)
def _spylls_dictionary(lang: str = "hu_HU"):
    from spylls.hunspell import Dictionary
    found = find_dictionary(lang)
    if found is None:
        raise RuntimeError(
            f"No {lang} dictionary found. Install with: sudo apt install hunspell-hu "
            f"(or drop {lang}.dic/{lang}.aff into /usr/share/hunspell)."
        )
    dic, _aff = found
    return Dictionary.from_files(str(dic.with_suffix("")))


def check(lang: str, text: str) -> list[tuple[str, list[str]]]:
    """Return [(word, suggestions)] for misspelled words; [] when unavailable."""
    import re
    words = re.findall(r"[\w\u00c0-\u017f']+", text, flags=re.UNICODE)
    if not words:
        return []
    if backend() == "spylls":
        try:
            dictionary = _spylls_dictionary(lang)
        except Exception:
            return []
        out: list[tuple[str, list[str]]] = []
        for word in words:
            try:
                if not dictionary.lookup(word):
                    try:
                        sug = list(dictionary.suggest(word))[:5]
                    except Exception:
                        sug = []
                    out.append((word, [str(s) for s in sug]))
            except Exception:
                continue
        return out
    if backend() == "cyhunspell":
        try:
            import hunspell
            handle = hunspell.HunSpell(f"/usr/share/hunspell/{lang}.dic", f"/usr/share/hunspell/{lang}.aff")
        except Exception:
            return []
        out = []
        for word in words:
            try:
                if not handle.spell(word):
                    try:
                        sug = list(handle.suggest(word))[:5]
                    except Exception:
                        sug = []
                    out.append((word, sug))
            except Exception:
                continue
        return out
    return []
