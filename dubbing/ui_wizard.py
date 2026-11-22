"""Dubbing Studio wizard (Tk Toplevel). Imported lazily from App."""
from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BooleanVar
from tkinter import StringVar
from tkinter import Toplevel
from tkinter import filedialog
from tkinter import ttk

from . import SUPPORTED_INPUT_EXTS
from . import has_libass
from . import is_video_input
from .config import DEFAULT_DUBBING_SETTINGS
from .config import DubJob


class DubbingWizard:
    def __init__(self, app) -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.transient(app.root)
        self.window.title("Dubbing Studio — audio/video to dubbed version")
        self.window.geometry("1020x760")

        s = dict(app.settings.get("dubbing", {})) if isinstance(getattr(app, "settings", {}), dict) else {}
        self.target_lang = StringVar(value=str(s.get("target_lang", DEFAULT_DUBBING_SETTINGS["target_lang"])))
        self.engine = StringVar(value=str(app.engine.get()) if hasattr(app, "engine") else "Auto")
        self.input_path = StringVar(value="")
        self.burn_in = BooleanVar(value=False)
        self.separation = BooleanVar(value=bool(s.get("separation_enabled", False)))
        self.phase_1b = BooleanVar(value=bool(s.get("phase_1b_enabled", False)))
        self.status = StringVar(value="Idle — pick an audio/video file.")
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:  # pragma: no cover
        f = ttk.Frame(self.window, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Dubbing Studio", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="EN to HU local dub. Phase 1a: audio-only. Enable Phase 1b for video mux + burn-in.",
                  wraplength=900).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        ttk.Entry(row, textvariable=self.input_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse).pack(side="left", padx=6)
        opts = ttk.Frame(f)
        opts.pack(fill="x", pady=4)
        ttk.Label(opts, text="Target").pack(side="left")
        ttk.Combobox(opts, textvariable=self.target_lang, values=["hu", "en"], width=6,
                     state="readonly").pack(side="left", padx=6)
        ttk.Label(opts, text="Engine").pack(side="left")
        ttk.Combobox(opts, textvariable=self.engine, values=["Auto", "Piper", "XTTS v2", "Pocket TTS"],
                     width=12, state="readonly").pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="Background separation (experimental, CPU-heavy)",
                        variable=self.separation).pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="Phase 1b: video mux + burn-in", variable=self.phase_1b,
                        command=self._refresh).pack(side="left", padx=6)
        self.burn_btn = ttk.Checkbutton(f, text="Burn subtitles into video", variable=self.burn_in)
        self.burn_btn.pack(anchor="w", pady=4)
        ttk.Button(f, text="Transcribe + Translate (dry run)", command=self._start).pack(anchor="w", pady=4)
        ttk.Label(f, textvariable=self.status, wraplength=900).pack(anchor="w", pady=6)
        ttk.Button(f, text="Close", command=self._on_close).pack(anchor="e")
        self._refresh()

    def _refresh(self) -> None:
        video = bool(self.input_path.get()) and is_video_input(self.input_path.get())
        ok = video and bool(self.phase_1b.get()) and has_libass()
        try:
            self.burn_btn.state(["!disabled"] if ok else ["disabled"])
        except Exception:
            pass
        if not ok and self.burn_in.get():
            self.burn_in.set(False)

    def _browse(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_INPUT_EXTS))
        p = filedialog.askopenfilename(filetypes=[("Media", exts), ("All", "*.*")])
        if p:
            self.input_path.set(p)
            self._refresh()

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            job = DubJob(input=Path(self.input_path.get()), source_lang="en",
                         target_lang=self.target_lang.get(), engine=self.engine.get(),
                         burn_in=self.burn_in.get(), output_dir=Path.cwd() / "output")
            job.validate()
        except Exception as exc:
            self.status.set(f"Error: {exc}")
            return
        self.stop_event.clear()
        self.status.set("Working… (models download on first use after confirmation)")
        self.worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        self.worker.start()

    def _run_job(self, job: DubJob) -> None:
        import tempfile

        from .pipeline import DubPipeline
        try:
            with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
                pipe = DubPipeline(job, log=lambda m: self.window.after(0, lambda: self.status.set(m)))
                srt = pipe.run(Path(tmp))
            self.window.after(0, lambda: self.status.set(f"Done: {srt.name} (see output dir for full export)"))
        except InterruptedError:
            self.window.after(0, lambda: self.status.set("Stopped."))
        except Exception as exc:
            msg = str(exc)
            self.window.after(0, lambda m=msg: self.status.set(f"Error: {m}"))

    def _on_close(self) -> None:
        self.stop_event.set()
        try:
            self.window.destroy()
        except Exception:
            pass
