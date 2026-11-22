"""Video-only helpers (Phase 1b). Never imported by Phase 1a audio path."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import ffmpeg_path
from . import has_libass
from .subtitles import build_burn_filter
from .subtitles import soft_sub_mux_args


def mux_video(video: Path, audio_wav: Path, srt: Path, out: Path, burn_in: bool) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {out}")
    if burn_in:
        if not has_libass():
            raise RuntimeError("Burn-in needs libass subtitles filter; fell back to soft subs + sidecar.")
        filt = build_burn_filter(srt)
        cmd = [ffmpeg_path(), "-hide_banner", "-i", str(video), "-i", str(audio_wav),
               *filt, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-shortest", str(out)]
    else:
        sub_args = soft_sub_mux_args(srt, out.suffix)
        cmd = [ffmpeg_path(), "-hide_banner", "-i", str(video), "-i", str(audio_wav),
               "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2",
               "-c:v", "copy", "-c:a", "aac", *sub_args, "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"Video mux failed: {(proc.stderr or proc.stdout)[-2000:]}")
    return out
