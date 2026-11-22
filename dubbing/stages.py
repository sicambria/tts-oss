"""Concrete stage functions — real ffmpeg calls, optional ML behind explicit errors."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from . import ffmpeg_path
from .config import Segment

NLLB_MODEL_ENV = "DUB_NLLB_MODEL"
NLLB_DEFAULT_MODEL = "facebook/nllb-200-1.3B"

# Short-code <-> NLLB FLORES-200 code map for the pairs this app dubs.
_NLLB_BY_SHORT = {
    "en": "eng_Latn",
    "hu": "hun_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "pl": "pol_Latn",
    "nl": "nld_Latn",
    "cs": "ces_Latn",
    "tr": "tur_Latn",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "zh": "zho_Hans",
    "ko": "kor_Hang",
    "ja": "jpn_Jpan",
    "hi": "hin_Deva",
}
_WHISPER_BY_NLLB = {v: k for k, v in _NLLB_BY_SHORT.items()}


def nllb_code(lang: str) -> str:
    """Map 'en'/'hu' or already-mapped 'eng_Latn' to an NLLB code."""
    lang = (lang or "").strip()
    if not lang:
        raise ValueError("empty language code")
    if lang in _NLLB_BY_SHORT.values():
        return lang
    short = lang.split("_")[0].split("-")[0].lower()
    if short in _NLLB_BY_SHORT:
        return _NLLB_BY_SHORT[short]
    # Unknown: assume it is already a FLORES code and let the tokenizer reject it.
    return lang


def whisper_lang(lang: str | None) -> str | None:
    """Map 'eng_Latn'/'en' to Whisper ISO 'en'; None stays None (auto-detect)."""
    if lang is None:
        return None
    lang = lang.strip()
    if not lang:
        return None
    if lang in _WHISPER_BY_NLLB:
        return _WHISPER_BY_NLLB[lang]
    return lang.split("_")[0].split("-")[0].lower() or None


def nllb_model_id() -> str:
    return os.environ.get(NLLB_MODEL_ENV, NLLB_DEFAULT_MODEL)


def _ffmpeg(*args: str, timeout: int = 600) -> None:
    cmd = [ffmpeg_path(), "-hide_banner", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {(proc.stderr or proc.stdout)[-2000:]}")


def extract_audio(src: Path, tmp: Path, sr: int = 44100) -> Path:
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-y", "-i", str(src), "-vn", "-ar", str(sr), "-ac", "1", str(tmp))
    return tmp


ATEMPO_MIN, ATEMPO_MAX = 0.5, 2.0
OVERFLOW_RATIO = 2.5


def separate_background(wav: Path, tmp_dir: Path, enabled: bool) -> tuple[Path, Path | None]:
    """Split vocals (for STT) from accompaniment (for low-volume bg mix).

    Returns (vocal_wav, bg_wav|None). Disabled -> identity. Enabled requires
    the optional ``audio-separator`` dependency plus its vocal model
    (``Kim_Vocal_2.onnx`` ~300MB, downloaded on first use after the wizard
    confirms). Unit tests mock ``audio_separator.separator.Separator`` so no
    download happens in CI.
    """
    if not enabled:
        return wav, None
    try:
        from audio_separator.separator import Separator
    except Exception as exc:
        raise RuntimeError("Missing dependency: audio-separator. Install with: pip install -r requirements-dubbing.txt") from exc
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        sep = Separator(output_dir=str(tmp_dir), output_format="wav")
        sep.load_model(model_filename="Kim_Vocal_2.onnx")
        out_names = sep.separate(str(wav))
    except Exception as exc:
        raise RuntimeError(f"Vocal separation failed (model Kim_Vocal_2 ~300MB): {exc}") from exc
    vocal, bg = _pick_vocal_bg(tmp_dir, out_names, wav)
    return vocal, bg


def _pick_vocal_bg(tmp_dir: Path, out_names: list[str], fallback: Path) -> tuple[Path, Path | None]:
    """Map separator outputs to (vocals, accompaniment) by filename stem."""
    vocals: Path | None = None
    instrumental: Path | None = None
    for name in out_names or []:
        p = Path(name)
        if not p.is_absolute():
            p = tmp_dir / p
        stem = p.stem.lower()
        if "vocal" in stem and vocals is None:
            vocals = p
        elif "instrument" in stem and instrumental is None:
            instrumental = p
    if vocals is None or not vocals.is_file():
        return fallback, None
    return vocals, (instrumental if instrumental is not None and instrumental.is_file() else None)


def transcribe(vocal: Path, model_size: str = "small", language: str | None = None,
               vad_filter: bool = False) -> list[Segment]:
    """Transcribe vocals. `language` accepts 'en' or 'eng_Latn' (mapped to Whisper ISO).

    Defaults target music+speech input: VAD is OFF because Silero VAD drops
    sung vocals along with the music (proven on real song: VAD-on kept 5/52
    segments, losing the whole sung body). Hallucination on instrumental gaps
    is instead curbed with ``condition_on_previous_text=False`` +
    ``hallucination_silence_threshold``. Pass ``vad_filter=True`` for
    spoken-only content where music-only hallucinations dominate.
    """
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("Missing dependency: faster-whisper. Install with: pip install -r requirements-dubbing.txt") from exc
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    whisper_language = whisper_lang(language) if language else None
    kwargs: dict = dict(word_timestamps=True, vad_filter=vad_filter,
                        condition_on_previous_text=False,
                        hallucination_silence_threshold=2.0)
    if whisper_language:
        kwargs["language"] = whisper_language
    if vad_filter:
        kwargs["vad_parameters"] = dict(min_silence_duration_ms=500)
    try:
        segments, _ = model.transcribe(str(vocal), **kwargs)
    except TypeError:
        # Older faster-whisper without vad_filter/condition kwargs.
        fallback = dict(word_timestamps=True)
        if whisper_language:
            fallback["language"] = whisper_language
        segments, _ = model.transcribe(str(vocal), **fallback)
    return [Segment(start=float(s.start), end=float(s.end), text=(s.text or "").strip())
            for s in segments if (s.text or "").strip()]


def translate_segments(segs: list[Segment], src: str = "eng_Latn", tgt: str = "hun_Latn") -> list[Segment]:
    """Translate segment texts. Accepts short ('en'/'hu') or NLLB ('eng_Latn') codes."""
    try:
        import transformers
    except Exception as exc:
        raise RuntimeError("Missing dependency: transformers. Install with: pip install -r requirements-dubbing.txt") from exc
    src_code, tgt_code = nllb_code(src), nllb_code(tgt)
    model_id = nllb_model_id()
    try:
        tok = transformers.AutoTokenizer.from_pretrained(model_id)
        model = transformers.AutoModelForSeq2SeqLM.from_pretrained(model_id)
    except Exception as exc:
        raise RuntimeError(f"Could not load {model_id} (needs ~2.5GB download + license confirm): {exc}") from exc
    try:
        tok.src_lang = src_code
    except Exception:
        pass
    try:
        bos_id = tok.convert_tokens_to_ids(tgt_code)
    except Exception as exc:
        raise RuntimeError(f"Unknown NLLB target language '{tgt}': {exc}") from exc
    out = []
    for seg in segs:
        text = (seg.text or "").strip()
        if not text:
            seg.translated = ""
            out.append(seg)
            continue
        sp_len = len(tok(text).input_ids)
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
        gen = model.generate(**inputs, forced_bos_token_id=bos_id,
                             max_new_tokens=max(8, min(256, int(1.6 * sp_len))))
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


def concat_timeline(placed: list[tuple[Path, float]], total_dur: float, out: Path) -> Path:
    """Mix per-segment wavs at start offsets into one timeline wav."""
    import subprocess as _sp
    out.parent.mkdir(parents=True, exist_ok=True)
    if not placed:
        raise ValueError("No segments to mix.")
    if len(placed) == 1 and placed[0][1] <= 0.01:
        _ffmpeg("-y", "-i", str(placed[0][0]), "-c:a", "pcm_s16le", str(out))
        return out
    cmd: list[str] = [ffmpeg_path(), "-hide_banner", "-y"]
    filter_inputs: list[str] = []
    for idx, (wav, start) in enumerate(placed):
        cmd += ["-i", str(wav)]
        ms = max(0, int(round(start * 1000)))
        filter_inputs.append(f"[{idx}:a]adelay={ms}|{ms}[a{idx}]")
    mixed = "".join(f"[a{idx}]" for idx in range(len(placed)))
    filt = ";".join(filter_inputs) + (
        f";{mixed}amix=inputs={len(placed)}:duration=longest:normalize=0,"
        f"apad=whole_dur={total_dur:.3f},atrim=0:{total_dur:.3f}[out]"
    )
    cmd += ["-filter_complex", filt, "-map", "[out]", "-c:a", "pcm_s16le", str(out)]
    proc = _sp.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"Timeline mix failed: {(proc.stderr or proc.stdout)[-2000:]}")
    return out


def export_audio(wav: Path, out: Path, bitrate: str = "192k") -> Path:
    """Export timeline wav to mp3/wav/ogg."""
    out.parent.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower()
    if ext == ".wav":
        _ffmpeg("-y", "-i", str(wav), "-c:a", "pcm_s16le", str(out))
    elif ext == ".mp3":
        _ffmpeg("-y", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", bitrate, str(out))
    elif ext == ".ogg":
        _ffmpeg("-y", "-i", str(wav), "-codec:a", "libvorbis", "-q:a", "5", str(out))
    else:
        raise ValueError(f"Unsupported audio output '{ext}'.")
    return out


def make_tmp(prefix: str = "dub-") -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix=prefix)
