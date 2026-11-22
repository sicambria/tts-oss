"""Dub quality gates — importable logic (covered by pytest); scripts/ are thin CLIs."""
from __future__ import annotations

import json
import wave
from collections import Counter
from pathlib import Path

from .subtitles import parse_srt


def _wav_peak(path: Path) -> float:
    import struct
    with wave.open(str(path), "rb") as wf:
        n, width = wf.getnframes(), wf.getsampwidth()
        raw = wf.readframes(min(n, wf.getframerate() * 30))
    if not raw:
        return 0.0
    fmt = {1: "b", 2: "h", 4: "i"}.get(width, "h")
    step = width
    n_samples = len(raw) // step
    peak = 0
    for (v,) in struct.iter_unpack(f"<{fmt}", raw[:n_samples * step]):
        a = abs(v)
        if a > peak:
            peak = a
    full = float(2 ** (8 * width - 1))
    return peak / full if full else 0.0


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 44100)


def _wav_samples(path: Path, max_seconds: float = 3600.0) -> tuple[list[float], int]:
    import struct
    with wave.open(str(path), "rb") as wf:
        rate, width, n = wf.getframerate(), wf.getsampwidth(), wf.getnframes()
        frames = min(n, int(max_seconds * rate))
        raw = wf.readframes(frames)
    fmt = {1: "b", 2: "h", 4: "i"}.get(width, "h")
    full = float(2 ** (8 * width - 1))
    return [v / full for (v,) in struct.iter_unpack(f"<{fmt}", raw[:len(raw) // width * width])], rate


def vocal_coverage(work_dir: Path, floor: float = 0.01) -> dict:
    """Per-segment dubbed-energy coverage: for each SRT span, is there voice?

    Returns {'ratio': covered/total, 'silent': [idx,...]}. A silent span where
    the original sings is a dropped line (transcription miss or empty synth).
    """
    segs = parse_srt(work_dir / "dub.srt")
    tl = work_dir / "dub_timeline.wav"
    if not segs or not tl.is_file():
        return {"ratio": 0.0, "silent": [], "total": len(segs)}
    samples, rate = _wav_samples(tl)
    silent: list[int] = []
    for i, s in enumerate(segs):
        a, b = max(0, int(s.start * rate)), min(len(samples), int(s.end * rate))
        if b - a < rate // 20:
            b = min(len(samples), a + rate // 20)
        window = samples[a:b] if b > a else []
        import math
        rms = math.sqrt(sum(v * v for v in window) / len(window)) if window else 0.0
        if rms < floor:
            silent.append(i)
    total = len(segs)
    return {"ratio": (total - len(silent)) / total if total else 0.0,
            "silent": silent, "total": total}


def _extract_mono16k(media: Path, out: Path) -> Path:
    import subprocess as _sp

    from . import ffmpeg_path
    _sp.run([ffmpeg_path(), "-hide_banner", "-y", "-i", str(media),
             "-map", "0:a:0", "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(out)],
            check=True, capture_output=True, timeout=600)
    return out


def mux_audit(output_media: Path, mixed_wav: Path) -> dict:
    """Prove the DELIVERABLE's audio track is the dub, not the original.

    Extracts the output's audio track and correlates it against the dub mix.
    A correct mux scores ~0.99 (lossy-codec only); the classic burn-in bug
    (original audio kept) scores low because the signals differ. Fails closed
    on any extraction error.
    """
    import tempfile as _tf
    try:
        import numpy as _np
    except Exception as exc:
        return {"ok": False, "correlation": 0.0, "reason": f"numpy missing: {exc}"}
    try:
        with _tf.TemporaryDirectory(prefix="mux-audit-") as tmp:
            got = _extract_mono16k(Path(output_media), Path(tmp) / "got.wav")
            want = _extract_mono16k(Path(mixed_wav), Path(tmp) / "want.wav")
            a = _np.asarray(_wav_samples(got)[0], dtype=_np.float64)
            b = _np.asarray(_wav_samples(want)[0], dtype=_np.float64)
        n = min(len(a), len(b))
        if n < 16000:
            return {"ok": False, "correlation": 0.0, "reason": "too short to audit"}
        a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
        denom = float((_np.dot(a, a) * _np.dot(b, b)) ** 0.5)
        r = float(_np.dot(a, b) / denom) if denom > 0 else 0.0
        return {"ok": bool(r >= 0.90), "correlation": round(r, 4)}
    except Exception as exc:
        return {"ok": False, "correlation": 0.0, "reason": str(exc)[:300]}


def repeated_ngram_ratio(texts: list[str], n: int = 4) -> float:
    grams: Counter[str] = Counter()
    total = 0
    for t in texts:
        words = t.lower().split()
        for i in range(max(0, len(words) - n + 1)):
            grams[" ".join(words[i:i + n])] += 1
            total += 1
    if not total:
        return 0.0
    repeated = sum(c - 1 for c in grams.values() if c > 1)
    return repeated / total


def spell_unknown_rate(texts: list[str], lang: str = "hu_HU") -> dict:
    """Unknown-word rate via spylls; {'rate':..,'checked':bool} (checked False when no dict)."""
    try:
        from . import spellcheck
    except Exception:
        return {"rate": 0.0, "checked": False, "reason": "no spellcheck module"}
    try:
        if not spellcheck.available(lang):
            return {"rate": 0.0, "checked": False, "reason": "no dictionary"}
    except Exception:
        return {"rate": 0.0, "checked": False, "reason": "backend error"}
    words = [w.strip(".,!?;:\"'()[]-–—").lower() for t in texts for w in t.split()]
    words = [w for w in words if len(w) > 2]
    if not words:
        return {"rate": 0.0, "checked": True, "unknown": [], "total": 0}
    try:
        hits = spellcheck.check(lang, " ".join(words))
    except Exception:
        return {"rate": 0.0, "checked": False, "reason": "check failed"}
    bad = {w for w, _ in hits}
    return {"rate": len(bad) / len(words), "checked": True,
            "unknown": sorted(bad)[:20], "total": len(words)}


def check(work_dir: Path, source_media: Path | None = None) -> dict:
    """Run all gates on a pipeline work dir. Returns dict; 'ok' bool; caller exits accordingly."""
    work_dir = Path(work_dir)
    result: dict = {"ok": True, "failures": [], "work_dir": str(work_dir)}
    srt = work_dir / "dub.srt"
    if not srt.is_file():
        return {"ok": False, "failures": ["missing dub.srt"], "work_dir": str(work_dir)}
    try:
        segs = parse_srt(srt)
    except Exception as exc:
        return {"ok": False, "failures": [f"srt parse failed: {exc}"], "work_dir": str(work_dir)}
    # parse_srt stores text in .translated; also accept .text
    texts = [(s.translated or s.text or "") for s in segs]
    # EN sources live in dub_transcript.json (written by the pipeline); the
    # SRT carries only the translation. Truncation audit needs both.
    sources: list[str] = [(s.text or "") for s in segs]
    try:
        import json as _json
        tj = work_dir / "dub_transcript.json"
        if tj.is_file():
            rows = _json.loads(tj.read_text(encoding="utf-8"))
            if isinstance(rows, list) and len(rows) == len(segs):
                sources = [str(r.get("text") or "") for r in rows]
    except Exception:
        pass
    result["segments"] = len(segs)
    if not segs:
        result["ok"] = False
        result["failures"].append("zero segments")
        return result
    empty = [i for i, t in enumerate(texts) if not t.strip()]
    if empty:
        result["ok"] = False
        result["failures"].append(f"empty translations at segments {empty[:5]}")
    ngram = repeated_ngram_ratio([t for t in texts if t.strip()])
    result["repeated_ngram_ratio"] = round(ngram, 3)
    if ngram > 0.35:
        result["ok"] = False
        result["failures"].append(f"hallucination suspected: repeated {4}-gram ratio {ngram:.2f} > 0.35")
    truncated: list[int] = []
    for i, (src, tgt) in enumerate(zip(sources, texts)):
        if len(src) > 20 and len(tgt.strip()) < 0.5 * len(src):
            truncated.append(i)
    if truncated:
        result["ok"] = False
        result["failures"].append(f"truncated translations at segments {truncated[:8]} (HU <50% of EN chars)")
    spell = spell_unknown_rate([t for t in texts if t.strip()])
    result["spell"] = {k: v for k, v in spell.items() if k in ("rate", "checked", "total", "reason")}
    if spell.get("checked") and spell.get("rate", 0.0) > 0.40:
        result["ok"] = False
        result["failures"].append(f"spellcheck unknown-word rate {spell['rate']:.2f} > 0.40")
    tl = work_dir / "dub_timeline.wav"
    if tl.is_file():
        try:
            peak = _wav_peak(tl)
            dur = _wav_duration(tl)
        except Exception:
            peak, dur = 0.0, 0.0
        result["timeline_peak"] = round(peak, 4)
        result["timeline_dur_s"] = round(dur, 1)
        if peak < 0.005:
            result["ok"] = False
            result["failures"].append(f"timeline near-silence (peak {peak:.4f})")
    else:
        result["timeline_peak"] = None
    try:
        cov = vocal_coverage(work_dir)
    except Exception:
        cov = {"ratio": 0.0, "silent": [], "total": 0}
    result["vocal_coverage"] = round(cov.get("ratio", 0.0), 3)
    if cov.get("total"):
        result["silent_segments"] = cov.get("silent", [])
        if cov["ratio"] < 0.85:
            result["ok"] = False
            result["failures"].append(
                f"vocal coverage {cov['ratio']:.2f} < 0.85 (silent segs {cov['silent'][:8]})")
    if source_media is not None and tl.is_file():
        try:
            import subprocess

            from . import ffmpeg_path
            probe = subprocess.run(
                [ffmpeg_path(), "-hide_banner", "-i", str(source_media)],
                capture_output=True, text=True, timeout=60)
            out = (probe.stderr or "") + (probe.stdout or "")
            src_dur = None
            for line in out.splitlines():
                if "Duration:" in line:
                    ts = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = ts.split(":")
                    src_dur = int(h) * 3600 + int(m) * 60 + float(s)
                    break
            if src_dur:
                result["source_dur_s"] = round(src_dur, 1)
                lo, hi = src_dur * 0.75, src_dur * 1.25
                if not (lo <= dur <= hi + 2.0):
                    result["ok"] = False
                    result["failures"].append(
                        f"dub duration {dur:.1f}s outside ±25% of source {src_dur:.1f}s")
        except Exception:
            pass
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check dub work-dir quality gates.")
    ap.add_argument("--work", required=True, help="pipeline work dir containing dub.srt")
    ap.add_argument("--source", default=None, help="original media for duration check")
    args = ap.parse_args(argv)
    res = check(Path(args.work), Path(args.source) if args.source else None)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["ok"] else 1
