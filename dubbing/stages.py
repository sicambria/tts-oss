"""Concrete stage functions — real ffmpeg calls, optional ML behind explicit errors."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import ffmpeg_path
from .config import Segment

ATEMPO_MIN, ATEMPO_MAX = 0.5, 2.0
OVERFLOW_RATIO = 2.5


def _ffmpeg(*args: str, timeout: int = 600) -> None:
    cmd = [ffmpeg_path(), "-hide_banner", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {(proc.stderr or proc.stdout)[-2000:]}")


def extract_audio(src: Path, tmp: Path, sr: int = 44100) -> Path:
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-y", "-i", str(src), "-vn", "-ar", str(sr), "-ac", "1", str(tmp))
    return tmp


def separate_background(wav: Path, tmp_dir: Path, enabled: bool) -> tuple[Path, Path | None]:
    if not enabled:
        return wav, None
    try:
        import audio_separator  # noqa: F401
    except Exception as exc:
        raise RuntimeError("Missing dependency: audio-separator. Install with: pip install -r requirements-dubbing.txt") from exc
    raise RuntimeError("audio-separator model download requires user confirmation in the wizard (kim_vocal_2 ~300MB).")


def transcribe(vocal: Path, model_size: str = "small") -> list[Segment]:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("Missing dependency: faster-whisper. Install with: pip install -r requirements-dubbing.txt") from exc
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(vocal), word_timestamps=True)
    return [Segment(start=float(s.start), end=float(s.end), text=(s.text or "").strip()) for s in segments]


def translate_segments(segs: list[Segment], src: str = "eng_Latn", tgt: str = "hun_Latn") -> list[Segment]:
    try:
        import transformers
    except Exception as exc:
        raise RuntimeError("Missing dependency: transformers. Install with: pip install -r requirements-dubbing.txt") from exc
    model_id = "facebook/nllb-200-1.3B"
    try:
        tok = transformers.AutoTokenizer.from_pretrained(model_id)
        model = transformers.AutoModelForSeq2SeqLM.from_pretrained(model_id)
    except Exception as exc:
        raise RuntimeError(f"Could not load {model_id} (needs ~2.5GB download + license confirm): {exc}") from exc
    out = []
    for seg in segs:
        sp_len = len(tok(seg.text).input_ids)
        inputs = tok(seg.text, return_tensors="pt")
        gen = model.generate(**inputs, forced_bos_token_id=tok.convert_tokens_to_ids(tgt),
                             max_new_tokens=max(8, int(1.6 * sp_len)))
        seg.translated = tok.batch_decode(gen, skip_special_tokens=True)[0].strip()
        out.append(seg)
    return out


def atempo_chain(ratio: float) -> list[float]:
    """Split ratio into ffmpeg atempo filters each in [0.5, 2.0]."""
    if ratio <= 0:
        raise ValueError("ratio must be > 0")
    chain: list[float] = []
    r = ratio
    while r > ATEMPO_MAX:
        chain.append(ATEMPO_MAX)
        r /= ATEMPO_MAX
    while r < ATEMPO_MIN:
        chain.append(ATEMPO_MIN)
        r /= ATEMPO_MIN
    chain.append(r)
    return chain


def fit_to_slot(dub_wav: Path, slot_dur: float, work_dir: Path | None = None) -> tuple[Path, bool]:
    """Stretch dub_wav into slot_dur. Returns (path, overflow)."""
    import wave
    with wave.open(str(dub_wav), "rb") as wf:
        frames, rate = wf.getnframes(), wf.getframerate()
    dur = frames / float(rate or 44100)
    if slot_dur <= 0:
        return dub_wav, True
    r = dur / slot_dur
    if 0.85 <= r <= 1.15:
        return dub_wav, False
    overflow = r > OVERFLOW_RATIO
    chain = atempo_chain(min(r, 8.0))
    filt = ",".join(f"atempo={c:.6g}" for c in chain)
    out = (work_dir or dub_wav.parent) / f"{dub_wav.stem}_fit.wav"
    _ffmpeg("-y", "-i", str(dub_wav), "-filter:a", f"{filt},apad=whole_dur={slot_dur}", str(out))
    seg = out
    return seg, overflow


def mix_with_bg(dub: Path, bg: Path | None, keep_bg_ratio: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if bg is None:
        _ffmpeg("-y", "-i", str(dub), "-c:a", "pcm_s16le", str(out))
        return out
    bg_vol = max(0.0, min(1.0, keep_bg_ratio))
    _ffmpeg("-y", "-i", str(dub), "-i", str(bg),
            "-filter_complex", f"[1:a]volume={bg_vol}[bg];[0:a][bg]amix=inputs=2:duration=longest",
            "-c:a", "pcm_s16le", str(out))
    return out


def make_tmp(prefix: str = "dub-") -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix=prefix)
