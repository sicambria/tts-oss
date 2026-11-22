"""SRT helpers + ffmpeg burn-in / soft-sub mux args."""
from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

from .config import Segment


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


def build_burn_filter(srt: Path) -> list[str]:
    return ["-vf", f"subtitles={escape_sub_path(str(srt))}"]


def soft_sub_mux_args(srt: Path, out_ext: str) -> list[str]:
    if out_ext.lower().lstrip(".") == "mkv":
        return ["-c:s", "srt"]
    return ["-c:s", "mov_text"]
