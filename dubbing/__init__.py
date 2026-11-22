"""Local AV dubbing package — all heavy deps are optional lazy imports."""
from __future__ import annotations

SUPPORTED_INPUT_EXTS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mkv", ".avi", ".mov"})
SUPPORTED_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".avi", ".mov"})
SUPPORTED_AUDIO_EXTS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac"})

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
        import audio_separator  # noqa: F401
        return True
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
