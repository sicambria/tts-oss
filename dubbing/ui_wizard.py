"""Dubbing Studio wizard (Tk Toplevel). Imported lazily from App."""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import BooleanVar
from tkinter import StringVar
from tkinter import Text
from tkinter import Toplevel
from tkinter import filedialog
from tkinter import ttk

from . import SUPPORTED_INPUT_EXTS
from . import has_libass
from . import is_video_input
from . import missing_dependencies
from .config import DEFAULT_DUBBING_SETTINGS
from .config import DubJob


class DubbingWizard:
    def __init__(self, app) -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.transient(app.root)
        self.window.title("Dubbing Studio — audio/video to dubbed version")
        self.window.geometry("1020x820")

        s = dict(app.settings.get("dubbing", {})) if isinstance(getattr(app, "settings", {}), dict) else {}
        self.target_lang = StringVar(value=str(s.get("target_lang", DEFAULT_DUBBING_SETTINGS["target_lang"])))
        self.engine = StringVar(value=str(app.engine.get()) if hasattr(app, "engine") else "Auto")
        self.input_path = StringVar(value="")
        self.burn_in = BooleanVar(value=False)
        self.separation = BooleanVar(value=bool(s.get("separation_enabled", False)))
        self.phase_1b = BooleanVar(value=bool(s.get("phase_1b_enabled", False)))
        self.status = StringVar(value="Idle — pick an audio/video file.")
        self.install_status = StringVar(value="")
        self.worker: threading.Thread | None = None
        self.installer: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.log_lines: list[str] = []
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._build_ui()
        self._poll_log_queue()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_deps()

    # ----- logging (copy-pasteable) -----
    def _log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.log_lines.append(line)
        self._log_queue.put(line)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                try:
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", line + "\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                except Exception:
                    pass
                self.status.set(line[-220:])
        except queue.Empty:
            pass
        try:
            self.window.after(200, self._poll_log_queue)
        except Exception:
            pass

    def _copy_all(self) -> None:
        text = "\n".join(self.log_lines) or self.status.get()
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.install_status.set(f"Copied {len(self.log_lines)} log lines to clipboard.")
        except Exception as exc:
            self.install_status.set(f"Copy failed: {exc}")

    # ----- dependency panel + one-click pip install (no sudo) -----
    def _refresh_deps(self) -> None:
        try:
            for row in self.dep_tree.get_children():
                self.dep_tree.delete(row)
        except Exception:
            return
        try:
            deps = missing_dependencies(bool(self.separation.get()))
        except Exception as exc:
            self._log(f"ERROR checking dependencies: {exc}")
            return
        missing_pip = [d for d in deps if not d["ok"] and d["pip"] and not d["needs_sudo"]]
        for dep in deps:
            state = "OK" if dep["ok"] else ("MISSING (sudo needed)" if dep["needs_sudo"] else "MISSING (pip)")
            try:
                self.dep_tree.insert("", "end", values=(dep["label"], state, dep["hint"]))
            except Exception:
                pass
        try:
            if missing_pip and not (self.installer and self.installer.is_alive()):
                self.install_btn.state(["!disabled"])
                self.install_status.set(f"{len(missing_pip)} pip package(s) missing — one click installs, no sudo needed.")
            elif not missing_pip:
                self.install_btn.state(["disabled"])
                sudo_missing = [d["label"] for d in deps if not d["ok"] and d["needs_sudo"]]
                if sudo_missing:
                    self.install_status.set("Pip deps OK. System item(s) still missing (need sudo, see hint — copy the command).")
                else:
                    self.install_status.set("All dependencies OK.")
            self._refresh()
        except Exception:
            pass

    def _install_pip_deps(self) -> None:
        if self.installer and self.installer.is_alive():
            return
        try:
            from . import pip_missing_specs
            specs = pip_missing_specs(bool(self.separation.get()))
        except Exception as exc:
            self._log(f"ERROR resolving pip specs: {exc}")
            return
        if not specs:
            self.install_status.set("Nothing pip-installable is missing.")
            return
        self.install_status.set(f"Installing: {' '.join(specs)} …")
        self._log(f"INSTALL: {sys.executable} -m pip install {' '.join(specs)}")
        self.installer = threading.Thread(target=self._run_pip_install, args=(specs,), daemon=True)
        self.installer.start()

    def _run_pip_install(self, specs: list[str]) -> None:
        try:
            self.window.after(0, lambda: self.install_btn.state(["disabled"]))
        except Exception:
            pass
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", *specs],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self._log_queue.put("pip: " + line.rstrip())
            proc.wait(timeout=1800)
            if proc.returncode == 0:
                self._log("INSTALL OK — re-checking dependencies.")
            else:
                self._log(f"ERROR: pip exited with code {proc.returncode}. Copy this log for help.")
        except Exception as exc:
            self._log(f"ERROR during pip install (no sudo was used): {exc}. Copy this log for help.")
        try:
            self.window.after(0, self._refresh_deps)
        except Exception:
            pass

    def _build_ui(self) -> None:  # pragma: no cover
        f = ttk.Frame(self.window, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Dubbing Studio", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="EN to HU local dub. Phase 1a: audio-only. Enable Phase 1b for video mux + burn-in.",
                  wraplength=900).pack(anchor="w", pady=(0, 8))

        dep_frame = ttk.LabelFrame(f, text="Dependencies (one-click pip install, no sudo)", padding=8)
        dep_frame.pack(fill="x", pady=(0, 8))
        self.dep_tree = ttk.Treeview(dep_frame, columns=("component", "status", "hint"),
                                     show="headings", height=5)
        self.dep_tree.heading("component", text="Component")
        self.dep_tree.heading("status", text="Status")
        self.dep_tree.heading("hint", text="How to fix")
        self.dep_tree.column("component", width=280)
        self.dep_tree.column("status", width=170)
        self.dep_tree.column("hint", width=430)
        self.dep_tree.pack(fill="x")
        dep_btns = ttk.Frame(dep_frame)
        dep_btns.pack(fill="x", pady=(6, 0))
        self.install_btn = ttk.Button(dep_btns, text="Install missing pip packages (no sudo)",
                                      command=self._install_pip_deps)
        self.install_btn.pack(side="left")
        ttk.Button(dep_btns, text="Re-check", command=self._refresh_deps).pack(side="left", padx=6)
        ttk.Button(dep_btns, text="Copy all messages", command=self._copy_all).pack(side="left", padx=6)
        ttk.Label(dep_btns, textvariable=self.install_status, wraplength=500).pack(side="left", padx=8)

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
                        variable=self.separation, command=self._refresh_deps).pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="Phase 1b: video mux + burn-in", variable=self.phase_1b,
                        command=self._refresh).pack(side="left", padx=6)
        self.burn_btn = ttk.Checkbutton(f, text="Burn subtitles into video", variable=self.burn_in)
        self.burn_btn.pack(anchor="w", pady=4)
        ttk.Button(f, text="Transcribe + Translate (dry run)", command=self._start).pack(anchor="w", pady=4)

        log_frame = ttk.LabelFrame(f, text="Log — every error lands here, Copy all messages copies it", padding=6)
        log_frame.pack(fill="both", expand=True, pady=4)
        self.log_text = Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        ttk.Label(f, textvariable=self.status, wraplength=900).pack(anchor="w", pady=2)
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
            self._log(f"Input: {p}")
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
            self._log(f"ERROR: {exc}")
            return
        self.stop_event.clear()
        self._log("Working… (models download on first use after confirmation)")
        self.worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        self.worker.start()

    def _run_job(self, job: DubJob) -> None:
        import tempfile

        from .pipeline import DubPipeline
        try:
            with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
                pipe = DubPipeline(job, log=self._log_threadsafe)
                srt = pipe.run(Path(tmp))
            self._log(f"Done: {srt.name} (see output dir for full export)")
        except InterruptedError:
            self._log("Stopped.")
        except Exception as exc:
            self._log(f"ERROR: {exc}")

    def _log_threadsafe(self, msg: str) -> None:
        try:
            self.window.after(0, lambda m=msg: self._log(m))
        except Exception:
            self._log(msg)

    def _on_close(self) -> None:
        self.stop_event.set()
        try:
            if self.app is not None and isinstance(getattr(self.app, "settings", None), dict):
                self.app.settings.setdefault("dubbing", {}).update({
                    "target_lang": self.target_lang.get(),
                    "separation_enabled": bool(self.separation.get()),
                    "phase_1b_enabled": bool(self.phase_1b.get()),
                })
                try:
                    from app import save_app_settings
                    save_app_settings(self.app.settings)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
