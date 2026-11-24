"""SRT helpers + ffmpeg burn-in / soft-sub mux args."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from .config import Segment

_SUB_COLOR_RE = re.compile(r"&H[0-9A-Fa-f]{8}")


def build_subtitle_style(size: object = 20, color: object = "&H00FFFFFF", outline: object = 2) -> str:
    """Build a libass ``force_style`` value. Pure: no Tk, testable.

    Raises ``ValueError`` on out-of-range input so misconfigurations fail
    loudly at dub start instead of silently burning unstyled subs.
    """
    try:
        size_i = int(size)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"subtitle font size must be an integer: {size!r}") from exc
    if not 12 <= size_i <= 32:
        raise ValueError(f"subtitle font size must be within [12, 32]: {size_i}")
    color_s = str(color).strip()
    if not _SUB_COLOR_RE.fullmatch(color_s):
        raise ValueError(f"subtitle color must be ASS &HAABBGGRR: {color!r}")
    try:
        outline_i = int(outline)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"subtitle outline must be an integer: {outline!r}") from exc
    if not 0 <= outline_i <= 4:
        raise ValueError(f"subtitle outline must be within [0, 4]: {outline_i}")
    return f"FontSize={size_i},PrimaryColour={color_s},Outline={outline_i}"


def _ts(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[Segment], path: Path, translated: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = seg.translated if translated else seg.text
        lines.append(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{text.strip()}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_srt(path: Path) -> list[Segment]:
    import re
    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", raw.strip())
    out: list[Segment] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = re.match(r"(\S+)\s+-->\s+(\S+)", lines[1] if lines[0].strip().isdigit() else lines[0])
        if not m:
            continue
        text = "\n".join(lines[2:] if lines[0].strip().isdigit() else lines[1:])
        out.append(Segment(start=_parse_ts(m.group(1)), end=_parse_ts(m.group(2)), translated=text))
    return out


def _parse_ts(ts: str) -> float:
    ts = ts.replace(".", ",")
    hms, ms = ts.split(",")
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms) / 1000.0


def srt_norm_hash(segments: list[Segment]) -> str:
    """sha256 over NFC-normalized ms-rounded (start,end,text) — not raw bytes."""
    norm = []
    for seg in segments:
        text = unicodedata.normalize("NFC", (seg.translated or seg.text).strip())
        norm.append(f"{int(round(seg.start*1000))}|{int(round(seg.end*1000))}|{text}")
    return hashlib.sha256("\n".join(norm).encode("utf-8")).hexdigest()


def escape_sub_path(path: str) -> str:
    p = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"'{p}'"


def build_burn_filter(srt: Path, style: str | None = None) -> list[str]:
    """ffmpeg ``-vf`` args for burn-in. ``style`` is a pre-validated
    ``force_style`` value (see ``build_subtitle_style``); it is single-quoted
    and contains no commas/colons by construction, so the single ``-vf`` arg
    stays intact even for adversarial subtitle paths."""
    base = f"subtitles={escape_sub_path(str(srt))}"
    if style:
        return ["-vf", base + f":force_style='{style}'"]
    return ["-vf", base]


def soft_sub_mux_args(srt: Path, out_ext: str) -> list[str]:
    if out_ext.lower().lstrip(".") == "mkv":
        return ["-c:s", "srt"]
    return ["-c:s", "mov_text"]
