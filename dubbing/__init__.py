"""Local AV dubbing package — all heavy deps are optional lazy imports."""
from __future__ import annotations

SUPPORTED_INPUT_EXTS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mkv", ".avi", ".mov"})
SUPPORTED_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".avi", ".mov"})
SUPPORTED_AUDIO_EXTS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac"})

# Languages Dubbing Studio can translate between (NLLB-200 + XTTS v2 cover
# the same set; Whisper transcribes all of them). Order matches the main
# app's language menu.
DUBBING_LANGUAGES: tuple[str, ...] = (
    "en", "hu", "fr", "de", "pt", "it", "es", "pl",
    "tr", "ru", "nl", "cs", "ar", "zh", "ko", "ja", "hi",
)

DUBBING_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hu": "Hungarian",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "es": "Spanish",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "nl": "Dutch",
    "cs": "Czech",
    "ar": "Arabic",
    "zh": "Chinese",
    "ko": "Korean",
    "ja": "Japanese",
    "hi": "Hindi",
}


def dub_language_label(code: str) -> str:
    """Human-readable label for a dubbing language code, e.g. 'Hungarian (hu)'."""
    code = (code or "").strip().lower()
    return f"{DUBBING_LANGUAGE_NAMES.get(code, code.upper())} ({code})"


def dub_language_code(label: str) -> str:
    """Parse a label produced by dub_language_label back to its code."""
    text = (label or "").strip().lower()
    if text in DUBBING_LANGUAGE_NAMES:
        return text
    if text.endswith(")") and "(" in text:
        inner = text.rsplit("(", 1)[1].rstrip(")").strip()
        if inner:
            return inner
    return text.split("_")[0].split("-")[0] or "en"

__all__ = [
    "SUPPORTED_INPUT_EXTS", "SUPPORTED_VIDEO_EXTS", "SUPPORTED_AUDIO_EXTS",
    "ffmpeg_path", "has_libass", "has_faster_whisper", "has_nllb",
    "has_separator", "has_cyhunspell", "is_video_input",
]


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg") or "ffmpeg"


def is_video_input(path: str) -> bool:
    from pathlib import Path
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTS


def _run(exe: str, *args: str) -> tuple[int, str]:
    import subprocess
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:
        return 1, str(exc)


_libass_cache: bool | None = None


def has_libass() -> bool:
    """Two-part gate: filter exists mentioning libass AND functional 1s burn-in."""
    global _libass_cache
    if _libass_cache is not None:
        return _libass_cache
    exe = ffmpeg_path()
    code, out = _run(exe, "-hide_banner", "-h", "filter=subtitles")
    if code != 0 or "libass" not in out.lower():
        _libass_cache = False
        return False
    # Cached functional test: 1s color clip with a tiny SRT.
    import tempfile
    from pathlib import Path
    try:
        with tempfile.TemporaryDirectory(prefix="dub-libass-") as tmp:
            srt = Path(tmp) / "probe.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nProbe\n", encoding="utf-8")
            out_mp4 = Path(tmp) / "probe.mp4"
            import subprocess
            cmd = [exe, "-hide_banner", "-y", "-f", "lavfi", "-i",
                   "color=c=blue:s=160x120:d=1:r=10",
                   "-vf", f"subtitles={_escape_sub_path(str(srt))}",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            _libass_cache = proc.returncode == 0 and out_mp4.is_file()
            return _libass_cache
    except Exception:
        _libass_cache = False
        return False


def _escape_sub_path(path: str) -> str:
    # ffmpeg subtitles filter escaping: backslash, colon, single-quote; drive colon on Windows.
    p = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"'{p}'"


def has_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def has_nllb() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def has_separator() -> bool:
    try:
        from audio_separator.separator import Separator  # noqa: F401
        return True
    except Exception:
        pass
    # Isolated env (repo venv stays pinned to numpy 1.26.4 for Piper/gruut).
    try:
        from dubbing.stages import _separator_cli
        return _separator_cli() is not None
    except Exception:
        return False


def has_xtts() -> bool:
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        return False


def has_spellcheck() -> bool:
    """True when any no-sudo spell backend works (spylls primary, cyhunspell legacy)."""
    try:
        from . import spellcheck
        return spellcheck.backend() is not None
    except Exception:
        return False


def has_cyhunspell() -> bool:
    try:
        import hunspell  # noqa: F401  # cyhunspell installs as hunspell
        return True
    except Exception:
        try:
            import cyhunspell  # noqa: F401
            return True
        except Exception:
            return False


def missing_dependencies(separation_enabled: bool = False, engine: str = "") -> list[dict]:
    """Structured dep status for the wizard. pip items need no sudo; dicts may.

    NOTE: audio-separator is deliberately NOT pip-installable here — it needs
    numpy>=2 while this repo pins numpy 1.26.4 (Piper/gruut). It lives in an
    isolated env (scripts/setup_separator_env.sh) and auto-installs on job
    start. Never re-add a pip spec for it (regression: venv pollution).
    """
    """Structured dep status for the wizard. pip items need no sudo; dicts may."""
    items: list[dict] = []
    items.append({
        "key": "faster-whisper", "label": "Transcription (faster-whisper)",
        "ok": has_faster_whisper(), "pip": "faster-whisper==1.2.1",
        "needs_sudo": False,
        "hint": "pip install -r requirements-dubbing.txt",
    })
    try:
        import transformers  # noqa: F401
        nllb_ok = True
    except Exception:
        nllb_ok = False
    items.append({
        "key": "nllb", "label": "Translation (transformers + NLLB-200-1.3B)",
        "ok": nllb_ok, "pip": "transformers==4.46.3 sentencepiece",
        "needs_sudo": False,
        "hint": "pip install -r requirements-dubbing.txt (model ~2.5GB downloads after confirm)",
    })
    items.append({
        "key": "spellcheck", "label": "Spellcheck (spylls, pure-Python wheel)",
        "ok": has_spellcheck(), "pip": "spylls==0.1.7",
        "needs_sudo": False,
        "hint": "pip install -r requirements-dubbing.txt (reads system hunspell-hu dicts, no build).",
    })
    try:
        from . import spellcheck
        dict_ok = spellcheck.available("hu_HU")
    except Exception:
        dict_ok = False
    items.append({
        "key": "hu_dict", "label": "Hungarian dictionary (hu_HU)",
        "ok": dict_ok, "pip": "",
        "needs_sudo": True,
        "hint": "Usually preinstalled; if missing: sudo apt install hunspell-hu (reads /usr/share/hunspell/hu_HU.dic).",
    })
    if separation_enabled:
        items.append({
            "key": "separator", "label": "Music separation (isolated env, keeps music)",
            "ok": has_separator(), "pip": "",
            "needs_sudo": False,
            "hint": "Auto-installs on dub start (~1GB into ~/.cache/tts-oss-sep, no sudo); "
                    "or run scripts/setup_separator_env.sh now.",
        })
    if "xtts" in engine.lower():
        items.append({
            "key": "xtts", "label": "Voice cloning (Coqui XTTS v2)",
            "ok": has_xtts(), "pip": "TTS==0.22.0",
            "needs_sudo": False,
            "hint": "pip install -r requirements.txt (model auto-downloads on first use).",
        })
    items.append({
        "key": "libass", "label": "Subtitle burn-in (libass, bundled ffmpeg)",
        "ok": has_libass(), "pip": "",
        "needs_sudo": False,
        "hint": "Bundled imageio-ffmpeg 7.0.2 includes libass; if missing, use soft subs + sidecar.",
    })
    return items


CYHUNSPELL_SUDO_HINT = (
    "cyhunspell needs C build tools (no wheel on this platform): "
    "sudo apt install gettext libhunspell-dev pkg-config autoconf automake libtool, "
    "then retry. Dubbing works without it — spellcheck stays disabled."
)


def is_cyhunspell_build_failure(output: str) -> bool:
    markers = ("autopoint", "autoreconf", "hunspell.pc", "build_hunspell_package", "cyhunspell")
    low = output.lower()
    return any(m in low for m in markers)


def pip_missing_specs(separation_enabled: bool = False, engine: str = "") -> list[str]:
    out: list[str] = []
    for item in missing_dependencies(separation_enabled, engine):
        if not item["ok"] and item["pip"] and not item["needs_sudo"]:
            out.append(item["pip"])
    seen: list[str] = []
    for spec in out:
        for part in spec.split():
            if part not in seen:
                seen.append(part)
    return seen
