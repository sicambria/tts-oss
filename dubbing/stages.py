"""Concrete stage functions — real ffmpeg calls, optional ML behind explicit errors."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from . import ffmpeg_path
from .config import Segment

ATEMPO_MIN, ATEMPO_MAX = 0.5, 2.0
OVERFLOW_RATIO = 2.5
FIT_MAX_SQUEEZE = 1.5  # never speed speech more than 1.5x; spill over instead
SEPARATOR_MODEL = "Kim_Vocal_2.onnx"
SEPARATOR_VENV_DIR = "tts-oss-sep"  # under the platform cache dir (~/.cache/...)

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


def extract_audio(src: Path, tmp: Path, sr: int = 44100, channels: int = 1) -> Path:
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-y", "-i", str(src), "-vn", "-ar", str(sr), "-ac", str(channels), str(tmp))
    return tmp


def ensure_mono(wav: Path, tmp_dir: Path) -> Path:
    """Downmix to mono (Whisper input). No-op when already mono."""
    import wave as _wave
    try:
        with _wave.open(str(wav), "rb") as wf:
            if wf.getnchannels() == 1:
                return wav
    except Exception:
        return wav
    out = tmp_dir / f"{wav.stem}_mono.wav"
    _ffmpeg("-y", "-i", str(wav), "-ac", "1", str(out))
    return out


def _separator_cli() -> Path | None:
    """Isolated audio-separator console script (numpy>=2 lives outside the repo venv).

    Set DUB_SEPARATOR_PYTHON to override the interpreter explicitly.
    """
    import os as _os

    override = _os.environ.get("DUB_SEPARATOR_PYTHON", "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p
        return None
    cache = Path(_os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    cli = cache / SEPARATOR_VENV_DIR / ".venv" / "bin" / "audio-separator"
    return cli if cli.is_file() else None


def separate_background(wav: Path, tmp_dir: Path, enabled: bool) -> tuple[Path, Path | None]:
    """Split vocals (for STT) from accompaniment (for low-volume bg mix).

    Returns (vocal_wav, bg_wav|None). Disabled -> identity. Enabled tries the
    in-process ``audio_separator`` first (works in numpy>=2 environments),
    then the isolated ``tts-oss-sep`` venv console script (the repo venv is
    pinned to numpy 1.26 for Piper/gruut, which audio-separator 0.48 rejects).
    Build it once with ``scripts/setup_separator_env.sh``.
    """
    if not enabled:
        return wav, None
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        from audio_separator.separator import Separator
    except Exception as inproc_exc:
        cli = _separator_cli()
        if cli is None:
            raise RuntimeError(
                "Missing dependency: audio-separator (no in-process import and no isolated env). "
                "Run scripts/setup_separator_env.sh once (~1GB, numpy>=2 isolated from the repo venv)."
            ) from inproc_exc
        return _separate_via_cli(cli, wav, tmp_dir)
    try:
        sep = Separator(output_dir=str(tmp_dir), output_format="wav")
        sep.load_model(model_filename=SEPARATOR_MODEL)
        out_names = sep.separate(str(wav))
    except Exception as exc:
        raise RuntimeError(f"Vocal separation failed (model {SEPARATOR_MODEL} ~300MB): {exc}") from exc
    vocal, bg = _pick_vocal_bg(tmp_dir, out_names, wav)
    return ensure_mono(vocal, tmp_dir), bg


def _separate_via_cli(cli: Path, wav: Path, tmp_dir: Path) -> tuple[Path, Path | None]:
    """Run the isolated audio-separator CLI (first use downloads the model)."""
    import subprocess as _sp
    before = {p.name for p in tmp_dir.glob("*.wav")}
    cmd = [str(cli), str(wav), "--model_filename", SEPARATOR_MODEL,
           "--output_dir", str(tmp_dir), "--output_format", "wav"]
    try:
        proc = _sp.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception as exc:
        raise RuntimeError(f"Separator subprocess failed to start: {exc}") from exc
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-2000:]
        raise RuntimeError(f"Separator subprocess failed: {tail}")
    after = sorted(p.name for p in tmp_dir.glob("*.wav") if p.name not in before)
    vocal, bg = _pick_vocal_bg(tmp_dir, after, wav)
    return ensure_mono(vocal, tmp_dir), bg


def _pick_vocal_bg(tmp_dir: Path, out_names: list[str], fallback: Path) -> tuple[Path, Path | None]:
    """Map separator outputs to (vocals, accompaniment) by filename stem.

    audio-separator labels stems ``name_(Vocals)_Model.wav`` — match the
    parenthesized label, NOT a bare "vocal" substring (the model filename
    itself, e.g. Kim_Vocal_2, contains "vocal" and matches every stem).
    """
    import re as _re
    vocals: Path | None = None
    instrumental: Path | None = None
    unlabeled: list[Path] = []
    for name in out_names or []:
        p = Path(name)
        if not p.is_absolute():
            p = tmp_dir / p
        stem = p.stem.lower()
        label = _re.search(r"\((vocals?|instrumental|karaoke|accompaniment)\)", stem)
        if label:
            kind = label.group(1)
            if kind.startswith("vocal") and vocals is None:
                vocals = p
            elif instrumental is None:
                instrumental = p
        else:
            unlabeled.append(p)
    if vocals is None:
        # No parenthesized labels: bare-substring fallback on the basename
        # only (never the model suffix).
        for p in unlabeled:
            base = _re.sub(r"_kim_vocal_2$", "", p.stem.lower())
            if "vocal" in base and vocals is None:
                vocals = p
            elif "instrument" in base and instrumental is None:
                instrumental = p
    if vocals is None or not vocals.is_file():
        return fallback, None
    return vocals, (instrumental if instrumental is not None and instrumental.is_file() else None)


def defuse_repetition(text: str, thresh: int = 6, keep: int = 2) -> str:
    """Collapse pathological decoder loops ("ma'am x30" -> "ma'am, ma'am").

    Greedy decoding (temperature=0) occasionally sticks on one word for a whole
    segment. Legitimate refrains repeat a word far fewer than `thresh` times
    in a row, so only true loops are cut. Case/punctuation-insensitive.
    """
    words = text.split()
    out: list[str] = []
    run_key: str | None = None
    run_len = 0
    for w in words:
        key = w.strip(".,!?;:\"'()[]").lower()
        if key and key == run_key:
            run_len += 1
            if run_len <= keep:
                out.append(w)
        else:
            run_key = key or None
            run_len = 1
            out.append(w)
    return " ".join(out)


def transcribe(vocal: Path, model_size: str = "small", language: str | None = None,
               vad_filter: bool = False) -> list[Segment]:
    """Transcribe vocals. `language` accepts 'en' or 'eng_Latn' (mapped to Whisper ISO).

    Deterministic greedy decoding (temperature=0.0) with OPEN confidence
    floors (log_prob -2.0, no_speech 1.0): fallback temperatures made runs
    nondeterministic (49/51/52 segs across runs) and strict floors dropped
    quiet tail verses; open floors recover them (proven: 180-238 s clip went
    from 7 to 12 segs, gaps stayed clean). Decoder loops are cut by
    defuse_repetition; instrumental-gap drift is curbed with
    condition_on_previous_text=False + hallucination_silence_threshold.
    The pipeline transcribes the MIX (complete, artifact-free gaps); the
    vocal STEM feeds only the bg mix and the clone reference. VAD stays
    available via parameter for spoken-only content.
    """
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("Missing dependency: faster-whisper. Install with: pip install -r requirements-dubbing.txt") from exc
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    whisper_language = whisper_lang(language) if language else None
    kwargs: dict = dict(word_timestamps=True, vad_filter=vad_filter,
                        condition_on_previous_text=False,
                        hallucination_silence_threshold=2.0,
                        temperature=0.0,
                        log_prob_threshold=-2.0, no_speech_threshold=1.0)
    if whisper_language:
        kwargs["language"] = whisper_language
    if vad_filter:
        kwargs["vad_parameters"] = dict(min_silence_duration_ms=500)
    try:
        segments, _ = model.transcribe(str(vocal), **kwargs)
    except TypeError:
        # Older faster-whisper without vad_filter/silence/temperature kwargs.
        fallback = dict(word_timestamps=True)
        if whisper_language:
            fallback["language"] = whisper_language
        segments, _ = model.transcribe(str(vocal), **fallback)
    try:
        segments, _ = model.transcribe(str(vocal), **kwargs)
    except TypeError:
        # Older faster-whisper without vad_filter/silence/temperature kwargs.
        fallback = dict(word_timestamps=True)
        if whisper_language:
            fallback["language"] = whisper_language
        segments, _ = model.transcribe(str(vocal), **fallback)
    cleaned: list[Segment] = []
    for s in segments:
        text = defuse_repetition((s.text or "").strip())
        if text:
            cleaned.append(Segment(start=float(s.start), end=float(s.end), text=text))
    return cleaned


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
                             max_new_tokens=max(32, min(256, int(2.0 * sp_len))),
                             no_repeat_ngram_size=3, repetition_penalty=1.2)
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


def merge_short_segments(segs: list[Segment], max_gap: float = 1.0,
                         min_dur: float = 1.5, max_span: float = 12.0) -> list[Segment]:
    """Merge sung micro-segments into singable phrases.

    Whisper slices songs into sub-second fragments (e.g. a 0.46 s "Mondd,
    mikor.") that no TTS can fit without chipmunk squeezing. A short slot
    absorbs following neighbours across < max_gap gaps until it reaches a
    singable length; long slots are left alone (capping merged spans at
    max_span so verses never fuse into 45 s mega-phrases). Merged phrases
    also translate better (full clause context). Timings stay exact (start
    of first, end of last), so sync is preserved.
    """
    if len(segs) < 2:
        return list(segs)
    merged = list(segs)
    while True:
        out = [merged[0]]
        changed = False
        for seg in merged[1:]:
            prev = out[-1]
            gap = seg.start - prev.end
            span = seg.end - prev.start
            if (gap < max_gap and prev.duration < min_dur * 2
                    and (prev.duration < min_dur or seg.duration < min_dur)
                    and span <= max_span):
                prev.end = max(prev.end, seg.end)
                prev.text = f"{prev.text} {seg.text}".strip()
                if seg.translated:
                    prev.translated = f"{prev.translated} {seg.translated}".strip()
                prev.overflow = prev.overflow or seg.overflow
                changed = True
            else:
                out.append(seg)
        merged = out
        if not changed:
            return merged


def fit_to_slot(dub_wav: Path, slot_dur: float, work_dir: Path | None = None) -> tuple[Path, bool]:
    """Place dub_wav into its time slot. Returns (path, overflow).

    Song-aware: a spoken HU translation is almost always SHORTER than its
    melodic slot, so the dub plays at natural speed from the slot start
    (onset = sync) with trailing silence — never slowed down. Only overlong
    dubs are touched: mild squeeze up to FIT_MAX_SQUEEZE to fit, beyond that
    the squeeze is capped and the tail spills past the slot (no cut, no
    chipmunk). overflow flags r > OVERFLOW_RATIO for the quality report.
    """
    import wave
    with wave.open(str(dub_wav), "rb") as wf:
        frames, rate = wf.getnframes(), wf.getframerate()
    dur = frames / float(rate or 44100)
    if slot_dur <= 0:
        return dub_wav, True
    r = dur / slot_dur
    if r <= 1.0:
        return dub_wav, False
    overflow = r > OVERFLOW_RATIO
    squeeze = min(r, FIT_MAX_SQUEEZE)
    chain = atempo_chain(squeeze)
    filt = ",".join(f"atempo={c:.6g}" for c in chain)
    out = (work_dir or dub_wav.parent) / f"{dub_wav.stem}_fit.wav"
    _ffmpeg("-y", "-i", str(dub_wav), "-filter:a", filt, str(out))
    return out, overflow


def mix_with_bg(dub: Path, bg: Path | None, keep_bg_ratio: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if bg is None:
        _ffmpeg("-y", "-i", str(dub), "-c:a", "pcm_s16le", str(out))
        return out
    bg_vol = max(0.0, min(1.0, keep_bg_ratio))
    # Normalize both inputs (dub may be mono 22/24 kHz TTS, bg stereo 44.1 kHz
    # stems) before amix, which requires identical rate/layout.
    _ffmpeg("-y", "-i", str(dub), "-i", str(bg),
            "-filter_complex",
            "[0:a]aresample=44100,aformat=channel_layouts=stereo[du];"
            f"[1:a]volume={bg_vol},aresample=44100,aformat=channel_layouts=stereo[bg];"
            "[du][bg]amix=inputs=2:duration=longest:normalize=0",
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
