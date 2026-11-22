"""DubPipeline orchestration with injectable stages (testable without models)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .config import DubJob
from .config import Segment

ExtractFn = Callable[[Path, Path], Path]


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
            synthesize=None) -> Path:
        from . import stages
        from . import subtitles
        self.job.validate()
        work_dir.mkdir(parents=True, exist_ok=True)
        self._check("start")

        extract = extract or stages.extract_audio
        wav = extract(self.job.input, work_dir / "extracted.wav")
        self.log(f"Extracted: {wav.name}")
        self._check("extract")

        vocal = wav
        if self.job.keep_bg_ratio > 0:
            from .stages import separate_background
            try:
                vocal, _bg = separate_background(wav, work_dir, False)
            except RuntimeError:
                vocal = wav

        transcribe = transcribe or stages.transcribe
        try:
            segments: list[Segment] = transcribe(vocal)
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc
        self.log(f"Transcribed {len(segments)} segments")
        self._check("transcribe")

        translate = translate or stages.translate_segments
        segments = translate(segments, self.job.source_lang, self.job.target_lang)
        self.job.segments = segments
        self._check("translate")

        srt = subtitles.write_srt(segments, work_dir / "dub.srt", translated=True)
        self.log(f"SRT: {srt.name}")
        return srt
