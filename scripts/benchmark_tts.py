#!/usr/bin/env python3
"""Benchmark all TTS engines in tts-oss on a one-page text."""
import sys
import time
import threading
import statistics
import json
import gc
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT)

import psutil
import soundfile as sf

import app as A
from app import (
    SynthesisRequest,
    ENGINE_PIPER,
    ENGINE_XTTS,
    ENGINE_POCKET,
)

OUT = Path("/tmp/opencode/bench_out")
OUT.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = Path("/tmp/opencode/bench_results.json")

PROSE = (
    "The weather had been unusually fine for several weeks, and the little "
    "town at the foot of the hills was busy with the work of the season. In "
    "the morning the farmers drove their carts through the main street, laden "
    "with hay and grain, while the children ran alongside, laughing at the "
    "dogs that chased the wheels. By midday the market square was full of "
    "colour and noise, and the women sold baskets of ripe fruit and fresh "
    "vegetables, their voices carrying above the general chatter. The old "
    "clock in the tower struck the hour, and everyone paused to listen, as if "
    "the town itself were drawing a breath. Then the bustle began again, and "
    "the afternoon passed in a pleasant confusion of arrivals and departures."
)


def build_text(target_words: int = 500) -> str:
    words = PROSE.split()
    sentences = []
    while sum(len(s.split()) for s in sentences) < target_words:
        for sentence in PROSE.replace(". ", ".|").replace("? ", "?|").replace("! ", "!|").split("|"):
            sentences.append(sentence.strip())
            if sum(len(s.split()) for s in sentences) >= target_words:
                break
    return " ".join(sentences)


TEXT = build_text()
N_WORDS = len(TEXT.split())
N_CHARS = len(TEXT)
print(f"[text] {N_WORDS} words, {N_CHARS} chars (~{N_CHARS/2500:.1f} page @ 2500 chars/page)")


class CpuSampler:
    def __init__(self, pid):
        self._p = psutil.Process(pid)
        self._samples = []
        self._stop = False

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        prev = None
        while not self._stop:
            try:
                t = self._p.cpu_times()
                now = time.time()
                if prev is not None:
                    dt = now - prev_t
                    if dt > 0:
                        used = (t.user - prev.user) + (t.system - prev.system)
                        self._samples.append((used / dt) * 100.0)
                prev, prev_t = t, now
            except Exception:
                pass
            time.sleep(0.1)

    def stop(self):
        self._stop = True
        self._thread.join(timeout=2)

    def stats(self):
        s = self._samples
        if not s:
            return {"mean_pct": 0.0, "peak_pct": 0.0, "cores_avg": 0.0, "cores_peak": 0.0}
        return {
            "mean_pct": round(statistics.mean(s), 1),
            "peak_pct": round(max(s), 1),
            "cores_avg": round(statistics.mean(s) / 100.0, 2),
            "cores_peak": round(max(s) / 100.0, 2),
        }


def audio_duration(path: Path) -> float:
    with sf.SoundFile(str(path)) as f:
        return f.frames / f.samplerate


def bench(name, make_request, synthesize_fn, preload_fn):
    result = {"engine": name, "words": N_WORDS, "chars": N_CHARS}
    proc = psutil.Process()
    pid = proc.pid

    # --- load (warm) phase ---
    rss_before = proc.memory_info().rss
    t0 = time.time()
    sampler = CpuSampler(pid)
    sampler.start()
    try:
        preload_fn()
    finally:
        sampler.stop()
    load_s = time.time() - t0
    rss_after_load = proc.memory_info().rss
    load_cpu = sampler.stats()

    # --- generation phase ---
    out = OUT / f"{name.replace(' ', '_')}.wav"
    if out.exists():
        out.unlink()
    request = make_request(out)
    rss_before_gen = proc.memory_info().rss
    t0 = time.time()
    sampler = CpuSampler(pid)
    sampler.start()
    try:
        synthesize_fn(request)
    finally:
        sampler.stop()
    gen_s = time.time() - t0
    rss_after_gen = proc.memory_info().rss
    gen_cpu = sampler.stats()

    duration = audio_duration(out)
    result.update(
        {
            "output_file": str(out),
            "audio_duration_s": round(duration, 2),
            "load_s": round(load_s, 2),
            "generate_s": round(gen_s, 2),
            "rtf_generate": round(gen_s / duration, 3) if duration else None,
            "rtf_total": round((load_s + gen_s) / duration, 3) if duration else None,
            "load_cpu": load_cpu,
            "gen_cpu": gen_cpu,
            "peak_rss_gb": round(max(rss_after_load, rss_after_gen) / 1e9, 2),
            "rss_delta_gb": round((rss_after_gen - rss_before_gen) / 1e9, 2),
        }
    )
    return result


def main():
    results = []

    def log(m):
        pass

    def run_isolated(name, bench_fn):
        try:
            return bench_fn()
        except Exception as exc:
            print(f"[{name}] FAILED: {exc}", file=sys.stderr)
            return {"engine": name, "error": str(exc)}

    def free(svc):
        del svc
        gc.collect()

    # --- Piper (smallest footprint first) ---
    svc = A.PiperService(log)
    voice_code = "en_US-lessac-medium"

    def pip_make(out):
        return SynthesisRequest(
            text=TEXT,
            language="en",
            output_file=out,
            engine=ENGINE_PIPER,
            piper_voice_label=voice_code,
            piper_voice_code=voice_code,
            speaker_name="",
            speaker_wav="",
        )

    def pip_preload():
        svc.ensure_loaded(voice_code)

    results.append(
        run_isolated(
            "Piper", lambda: bench("Piper en_US-lessac-medium", pip_make, svc.synthesize, pip_preload)
        )
    )
    free(svc)

    # --- Pocket TTS ---
    svc = A.PocketTTSService(log)

    def pocket_make(out):
        return SynthesisRequest(
            text=TEXT,
            language="en",
            output_file=out,
            engine=ENGINE_POCKET,
            piper_voice_label="",
            piper_voice_code="",
            speaker_name="alba",
            speaker_wav="",
        )

    def pocket_preload():
        svc.ensure_loaded("en")
        svc._get_voice_state("alba")

    results.append(
        run_isolated(
            "Pocket", lambda: bench("Pocket TTS (alba)", pocket_make, svc.synthesize, pocket_preload)
        )
    )
    free(svc)

    # --- XTTS v2 (heaviest footprint last, so it can't skew the others) ---
    svc = A.XTTSService(log)

    def xtts_make(out):
        return SynthesisRequest(
            text=TEXT,
            language="en",
            output_file=out,
            engine=ENGINE_XTTS,
            piper_voice_label="",
            piper_voice_code="",
            speaker_name=A.DEFAULT_SPEAKER,
            speaker_wav="",
        )

    results.append(
        run_isolated(
            "XTTS", lambda: bench("XTTS v2 (Ana Florence)", xtts_make, svc.synthesize, svc.ensure_loaded)
        )
    )
    free(svc)

    print()
    print(json.dumps(results, indent=2))
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"saved -> {RESULTS_FILE}")


if __name__ == "__main__":
    main()
