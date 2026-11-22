"""Dubbing job config + validation."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from . import SUPPORTED_INPUT_EXTS

DEFAULT_DUBBING_SETTINGS: dict[str, object] = {
    "target_lang": "hu",
    "engine": "Auto",
    "burn_in": False,
    "keep_bg_ratio": 0.2,
    "separation_enabled": False,
    "whisper_model": "small",
    "audio_output_format": "mp3",
    "video_output_format": "mp4",
    "phase_1b_enabled": False,
}


@dataclass
class Segment:
    start: float
    end: float
    text: str = ""
    translated: str = ""
    overflow: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class DubJob:
    input: Path
    source_lang: str = "en"
    target_lang: str = "hu"
    engine: str = "Auto"
    voice: str = ""
    ref_wav: str = ""
    segments: list[Segment] = field(default_factory=list)
    burn_in: bool = False
    keep_bg_ratio: float = 0.2
    output_dir: Path = field(default_factory=lambda: Path.cwd() / "output")
    audio_output_format: str = "mp3"
    video_output_format: str = "mp4"

    def validate(self) -> None:
        from . import SUPPORTED_AUDIO_EXTS
        from . import SUPPORTED_VIDEO_EXTS
        ext = self.input.suffix.lower()
        if ext not in SUPPORTED_INPUT_EXTS:
            raise ValueError(f"Unsupported input '{ext}'. Choose from: {sorted(SUPPORTED_INPUT_EXTS)}.")
        if self.target_lang.strip().lower() == "hu" and "pocket" in self.engine.lower():
            raise ValueError("Pocket TTS has no Hungarian voice. Use Piper or XTTS v2 for 'hu'.")
        out_ext = (self.video_output_format if ext in SUPPORTED_VIDEO_EXTS else self.audio_output_format).lower().lstrip(".")
        if self.burn_in and ext in SUPPORTED_AUDIO_EXTS:
            raise ValueError("Burn-in subtitles require a video input/output. Disable burn-in for audio-only.")
        if out_ext not in {"mp3", "wav", "mp4", "mkv"}:
            raise ValueError(f"Unsupported output format '{out_ext}'.")
