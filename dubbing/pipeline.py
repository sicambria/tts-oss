"""DubPipeline orchestration with injectable stages (testable without models)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .config import DubJob
from .config import Segment

ExtractFn = Callable[[Path, Path], Path]


def unique_output(base: Path) -> Path:
    if not base.exists():
        return base
    import time
    return base.with_name(f"{base.stem}_{time.strftime('%Y%m%d-%H%M%S')}{base.suffix}")


class DubPipeline:
    def __init__(self, job: DubJob, log: Callable[[str], None] = print,
                 pauser: threading.Event | None = None,
                 stopper: threading.Event | None = None) -> None:
        self.job = job
        self.log = log
        self.pause_event = pauser or threading.Event()
        self.pause_event.set()
        self.stop_event = stopper or threading.Event()

    def _check(self, stage: str) -> None:
        self.pause_event.wait()
        if self.stop_event.is_set():
            raise InterruptedError(f"Stopped at {stage}")

    def run(self, work_dir: Path,
            extract=None, transcribe=None, translate=None,
            synthesize=None, full: bool = False) -> Path:
        """Dry run (full=False) returns the SRT path. Full run returns final media."""
        from . import is_video_input
        from . import stages
        from . import subtitles
        self.job.validate()
        work_dir.mkdir(parents=True, exist_ok=True)
        self._check("start")

        extract = extract or stages.extract_audio
        wav = extract(self.job.input, work_dir / "extracted.wav")
        self.log(f"Extracted: {wav.name}")
        self._check("extract")

        separate = getattr(stages, "separate_background", None)
        if separate is not None:
            vocal, bg = separate(wav, work_dir, bool(getattr(self.job, "separation_enabled", False)))
        else:  # pragma: no cover - very old stages module
            vocal, bg = wav, None
        self.log(f"Vocal: {vocal.name}" + (f" + bg {bg.name}" if bg is not None else " (no separation)"))
        self._check("separate")

        transcribe = transcribe or stages.transcribe
        try:
            import inspect as _inspect
            params = set(_inspect.signature(transcribe).parameters)
            if params >= {"model_size", "language", "vad_filter"} or transcribe is stages.transcribe:
                segments: list[Segment] = transcribe(
                    vocal,
                    model_size=getattr(self.job, "whisper_model", "small"),
                    language=getattr(self.job, "source_lang", "en"),
                    # VAD off by default: it drops sung vocals with the music.
                    # Vocal separation (opt-in) is the music-content path; VAD
                    # stays available for spoken-only content via API.
                    vad_filter=False,
                )
            elif "model_size" in params:
                segments = transcribe(vocal, getattr(self.job, "whisper_model", "small"))
            else:
                segments = transcribe(vocal)
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc
        self.log(f"Transcribed {len(segments)} segments")
        self._check("transcribe")

        translate = translate or stages.translate_segments
        segments = translate(segments, self.job.source_lang, self.job.target_lang)
        self.job.segments = segments
        self._check("translate")

        srt = subtitles.write_srt(segments, work_dir / "dub.srt", translated=True)
        self.log(f"SRT: {srt.name} ({srt_norm_short(segments)})")
        if not full:
            return srt

        if synthesize is None:
            raise RuntimeError("Full dub needs a TTS synthesizer (pick an engine in the wizard).")
        if is_video_input(str(self.job.input)) and not getattr(self.job, "allow_video", False):
            raise RuntimeError("Video input needs Phase 1b enabled in the wizard.")

        placed: list[tuple[Path, float]] = []
        total_dur = max((s.end for s in segments), default=0.0)
        for idx, seg in enumerate(segments):
            self._check(f"synthesize {idx + 1}/{len(segments)}")
            raw = synthesize(seg.translated or seg.text, work_dir / f"seg_{idx:03d}.wav")
            fitted, overflow = stages.fit_to_slot(Path(raw), seg.duration, work_dir)
            seg.overflow = overflow
            if overflow:
                self.log(f"Segment {idx + 1} overflows its slot even squeezed — edit the translation shorter.")
            placed.append((fitted, seg.start))
        self.log(f"Synthesized + time-fit {len(placed)} segments")

        timeline = stages.concat_timeline(placed, max(total_dur, 0.1), work_dir / "dub_timeline.wav")
        self._check("timeline")
        mixed = stages.mix_with_bg(timeline, bg, self.job.keep_bg_ratio, work_dir / "dub_mixed.wav")

        if is_video_input(str(self.job.input)):
            from . import video as video_mod
            ext = (self.job.video_output_format or "mp4").lower().lstrip(".")
            if ext not in {"mp4", "mkv"}:
                ext = "mp4"
            out = unique_output(self.job.output_dir / f"{self.job.input.stem}_dubbed_{self.job.target_lang}.{ext}")
            out.parent.mkdir(parents=True, exist_ok=True)
            self.log(f"Muxing video (burn-in={'on' if self.job.burn_in else 'off'})…")
            return video_mod.mux_video(self.job.input, mixed, srt, out, self.job.burn_in)

        ext = (self.job.audio_output_format or "mp3").lower().lstrip(".")
        if ext not in {"mp3", "wav", "ogg"}:
            ext = "mp3"
        out = unique_output(self.job.output_dir / f"{self.job.input.stem}_dubbed_{self.job.target_lang}.{ext}")
        out.parent.mkdir(parents=True, exist_ok=True)
        return stages.export_audio(mixed, out)


def srt_norm_short(segments: list[Segment]) -> str:
    from .subtitles import srt_norm_hash
    return srt_norm_hash(segments)[:12]
