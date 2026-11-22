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


def _file_dialog_top(window, func, **kwargs):
    """Run a filedialog as a child of the wizard, forced above all windows.

    Native file dialogs without ``parent`` (or with a buried parent) can open
    below the wizard where the user never sees them.
    """
    try:
        window.deiconify()
    except Exception:
        pass
    try:
        window.lift()
    except Exception:
        pass
    try:
        window.attributes("-topmost", True)
    except Exception:
        pass
    try:
        window.update_idletasks()
    except Exception:
        pass
    try:
        return func(parent=window, **kwargs)
    finally:
        try:
            window.attributes("-topmost", False)
        except Exception:
            pass
        try:
            window.lift()
        except Exception:
            pass


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
        self.burn_in = BooleanVar(value=True)
        self.separation = BooleanVar(value=bool(s.get("separation_enabled", False)))
        self.phase_1b = BooleanVar(value=bool(s.get("phase_1b_enabled", False)))
        self.status = StringVar(value="Idle — pick an audio/video file.")
        self.install_status = StringVar(value="")
        self.worker: threading.Thread | None = None
        self.installer: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.log_lines: list[str] = []
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._deps_visible = True
        self._deps_user_shown = False
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
            self._update_deps_visibility(deps)
            self._refresh()
        except Exception:
            pass

    def _update_deps_visibility(self, deps: list[dict]) -> None:
        try:
            all_ok = bool(deps) and all(d.get("ok") for d in deps)
        except Exception:
            return
        if not all_ok:
            try:
                self._deps_user_shown = False
            except Exception:
                pass
            self._set_deps_visible(True, show_toggle=False)
        else:
            if getattr(self, "_deps_user_shown", False):
                self._set_deps_visible(True, show_toggle=True)
            else:
                self._set_deps_visible(False, show_toggle=True)

    def _set_deps_visible(self, visible: bool, show_toggle: bool = True) -> None:
        self._deps_visible = visible
        try:
            frame = getattr(self, "dep_frame", None)
            if frame is not None:
                if visible:
                    frame.pack(fill="x", pady=(0, 8))
                else:
                    frame.pack_forget()
        except Exception:
            pass
        try:
            btn = getattr(self, "dep_toggle_btn", None)
            if btn is not None:
                if show_toggle and not visible:
                    btn.pack(side="right")
                    try:
                        btn.configure(text="Show dependencies")
                    except Exception:
                        pass
                elif show_toggle and visible and getattr(self, "_deps_user_shown", False):
                    btn.pack(side="right")
                    try:
                        btn.configure(text="Hide dependencies")
                    except Exception:
                        pass
                elif not show_toggle:
                    btn.pack_forget()
        except Exception:
            pass

    def _toggle_deps(self) -> None:
        try:
            visible = not bool(getattr(self, "_deps_visible", True))
            self._deps_user_shown = visible
            self._set_deps_visible(visible, show_toggle=True)
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
        from . import CYHUNSPELL_SUDO_HINT
        from . import is_cyhunspell_build_failure
        try:
            self.window.after(0, lambda: self.install_btn.state(["disabled"]))
        except Exception:
            pass
        failed: list[str] = []
        for spec in specs:
            self._log(f"INSTALL: {spec}")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install", "--progress-bar", "off",
                     "--no-input", *spec.split()],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                )
                output_lines: list[str] = []
                assert proc.stdout is not None
                for line in proc.stdout:
                    clean = line.rstrip()
                    if clean:
                        output_lines.append(clean)
                        self._log_queue.put("pip: " + clean[-500:])
                proc.wait(timeout=1800)
                if proc.returncode == 0:
                    self._log(f"OK: {spec} installed.")
                else:
                    failed.append(spec)
                    tail = "\n".join(output_lines[-15:])
                    self._log(f"ERROR: pip exited code {proc.returncode} for {spec}.")
                    if tail:
                        self._log(f"pip tail for {spec}: ... {tail[-2000:]}")
                    if "cyhunspell" in spec and is_cyhunspell_build_failure(tail):
                        self._log(f"CYHUNSPELL BUILD FAILURE: {CYHUNSPELL_SUDO_HINT}")
            except Exception as exc:
                failed.append(spec)
                self._log(f"ERROR installing {spec} (no sudo was used): {exc}. Copy this log for help.")
        if not failed:
            self._log("INSTALL OK — re-checking dependencies.")
        else:
            ok = [s for s in specs if s not in failed]
            if ok:
                self._log(f"PARTIAL: installed [{', '.join(ok)}]; failed [{', '.join(failed)}] — dubbing works, failed parts stay disabled.")
            else:
                self._log(f"ERROR: all failed [{', '.join(failed)}]. Copy this log for help.")
        try:
            self.window.after(0, self._refresh_deps)
        except Exception:
            pass
        try:
            self.window.after(0, self._on_job_done)
        except Exception:
            pass

    def _build_ui(self) -> None:  # pragma: no cover
        f = ttk.Frame(self.window, padding=12)
        f.pack(fill="both", expand=True)
        header = ttk.Frame(f)
        header.pack(fill="x")
        ttk.Label(header, text="Dubbing Studio", font=("TkDefaultFont", 14, "bold")).pack(side="left", anchor="w")
        self.dep_toggle_btn = ttk.Button(header, text="Show dependencies", command=self._toggle_deps)
        self.dep_toggle_btn.pack(side="right")
        self.dep_toggle_btn.pack_forget()
        ttk.Label(f, text="EN to HU local dub. Phase 1a: audio-only. Enable Phase 1b for video mux + burn-in.",
                  wraplength=900).pack(anchor="w", pady=(0, 8))

        dep_frame = ttk.LabelFrame(f, text="Dependencies (one-click pip install, no sudo)", padding=8)
        dep_frame.pack(fill="x", pady=(0, 8))
        self.dep_frame = dep_frame
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
        out_row = ttk.Frame(f)
        out_row.pack(fill="x", pady=4)
        ttk.Label(out_row, text="Output folder").pack(side="left")
        try:
            default_out = str(self.app.settings.get("paths", {}).get("output_folder", Path.cwd() / "output"))
        except Exception:
            default_out = str(Path.cwd() / "output")
        self.output_folder = StringVar(value=default_out)
        ttk.Entry(out_row, textvariable=self.output_folder).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(out_row, text="Browse…", command=self._browse_out).pack(side="left")
        run_row = ttk.Frame(f)
        run_row.pack(fill="x", pady=4)
        self.dry_btn = ttk.Button(run_row, text="Transcribe + Translate (dry run)", command=self._start_dry)
        self.dry_btn.pack(side="left")
        self.full_btn = ttk.Button(run_row, text="Generate dubbed version (full)", command=self._start_full)
        self.full_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(run_row, text="Stop", command=self._on_stop)
        self.stop_btn.pack(side="left", padx=6)

        log_frame = ttk.LabelFrame(f, text="Log — every error lands here, Copy all messages copies it", padding=6)
        log_frame.pack(fill="both", expand=True, pady=4)
        self.log_text = Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        ttk.Label(f, textvariable=self.status, wraplength=900).pack(anchor="w", pady=2)
        ttk.Button(f, text="Close", command=self._on_close).pack(anchor="e")
        self._update_run_buttons()
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
        p = _file_dialog_top(self.window, filedialog.askopenfilename,
                             filetypes=[("Media", exts), ("All", "*.*")])
        if p:
            self.input_path.set(p)
            self._log(f"Input: {p}")
            self._refresh()

    def _browse_out(self) -> None:
        p = _file_dialog_top(self.window, filedialog.askdirectory)
        if p:
            self.output_folder.set(p)

    def _start_dry(self) -> None:
        self._start(full=False)

    def _start_full(self) -> None:
        self._start(full=True)

    def _start(self, full: bool) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            out_dir = Path(self.output_folder.get()).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                stored = dict(self.app.settings.get("dubbing", {})) if isinstance(
                    getattr(self.app, "settings", {}), dict) else {}
            except Exception:
                stored = {}
            job = DubJob(input=Path(self.input_path.get()), source_lang="en",
                         target_lang=self.target_lang.get(), engine=self.engine.get(),
                         burn_in=self.burn_in.get(), output_dir=out_dir,
                         allow_video=bool(self.phase_1b.get()),
                         separation_enabled=bool(self.separation.get()),
                         whisper_model=str(stored.get("whisper_model", DEFAULT_DUBBING_SETTINGS["whisper_model"])),
                         keep_bg_ratio=float(stored.get("keep_bg_ratio", DEFAULT_DUBBING_SETTINGS["keep_bg_ratio"])))
            job.validate()
            if full and is_video_input(str(job.input)) and not self.phase_1b.get():
                self._log("ERROR: video input needs Phase 1b enabled (checkbox above).")
                return
        except Exception as exc:
            self._log(f"ERROR: {exc}")
            return
        self.stop_event.clear()
        self._log("Working… (models download on first use after confirmation)")
        self._update_run_buttons()
        self.worker = threading.Thread(target=self._run_job, args=(job, full), daemon=True)
        self.worker.start()

    def _job_running(self) -> bool:
        try:
            return bool(self.worker is not None and self.worker.is_alive())
        except Exception:
            return False

    def _installer_running(self) -> bool:
        try:
            return bool(self.installer is not None and self.installer.is_alive())
        except Exception:
            return False

    def _update_run_buttons(self) -> None:
        running = self._job_running()
        for name, enabled_when in (("dry_btn", not running), ("full_btn", not running),
                                   ("stop_btn", running)):
            try:
                btn = getattr(self, name, None)
                if btn is not None:
                    btn.state(["!disabled"] if enabled_when else ["disabled"])
            except Exception:
                pass

    def _on_stop(self) -> None:
        self.stop_event.set()
        self._log("Stopping… (finishes the current step, then stops)")

    def _on_job_done(self) -> None:
        self._update_run_buttons()
        try:
            if self._job_running() or self._installer_running():
                self.window.title("Dubbing Studio — working… (close hides, job keeps running)")
            else:
                self.window.title("Dubbing Studio — audio/video to dubbed version")
        except Exception:
            pass

    def _app_synthesizer(self, work_dir: Path):
        """Build text->wav using the host app's TTS services (no app import)."""
        from app import DEFAULT_PIPER_VOICE_LABEL
        from app import ENGINE_POCKET
        from app import SynthesisRequest
        from app import get_piper_voice_metadata
        from app import pocket_default_voice
        from app import select_engine
        app = self.app
        language = self.target_lang.get()
        engine = self.engine.get()
        label = ""
        code = ""
        try:
            label = app.piper_voice_label.get().strip()
            metadata = app.piper_voice_options.get(label, get_piper_voice_metadata(label))
            code = metadata["code"]
        except Exception:
            label, code = DEFAULT_PIPER_VOICE_LABEL, "hu_HU-anna-medium"
        try:
            resolved = select_engine(engine, language, bool(app.speaker_wav.get().strip()), app.piper_voice_options)
        except Exception:
            resolved = engine
        try:
            speaker_name = (
                app.pocket_voice.get().strip() or pocket_default_voice(language)
                if resolved == ENGINE_POCKET
                else app.speaker_name.get().strip() or "Ana Florence"
            )
        except Exception:
            speaker_name = "Ana Florence"
        try:
            speaker_wav = app.speaker_wav.get().strip()
        except Exception:
            speaker_wav = ""
        try:
            speed = round(float(app.speed.get()), 1)
        except Exception:
            speed = 1.0
        counter = {"n": 0}

        def synth(text: str, out_hint: Path) -> Path:
            out = out_hint.parent / f"tts_{counter['n']:03d}.wav"
            counter["n"] += 1
            request = SynthesisRequest(
                text=text, language=language, output_file=out,
                engine=engine, piper_voice_label=label, piper_voice_code=code,
                speaker_name=speaker_name, speaker_wav=speaker_wav, speed=speed,
            )
            return Path(app.service.synthesize(request))

        return synth

    def _run_job(self, job: DubJob, full: bool = False) -> None:
        import tempfile

        from .pipeline import DubPipeline
        try:
            with tempfile.TemporaryDirectory(prefix="dub-") as tmp:
                tmp_path = Path(tmp)
                synth = self._app_synthesizer(tmp_path) if full else None
                pipe = DubPipeline(job, log=self._log_threadsafe, stopper=self.stop_event)
                out = pipe.run(tmp_path, synthesize=synth, full=full)
            self._log(f"Done: {out} (also wrote dub.srt next to it)")
        except InterruptedError:
            self._log("Stopped.")
        except Exception as exc:
            self._log(f"ERROR: {exc}")
        finally:
            try:
                self.window.after(0, self._on_job_done)
            except Exception:
                pass

    def _log_threadsafe(self, msg: str) -> None:
        try:
            self.window.after(0, lambda m=msg: self._log(m))
        except Exception:
            try:
                self._log(msg)
            except Exception:
                pass

    def _on_close(self) -> None:
        # A running job/install keeps going in the background: hide the window
        # instead of destroying it so reopening picks up live progress.
        if self._job_running() or self._installer_running():
            self._log("Window hidden — job keeps running in the background. Reopen Dubbing Studio to follow progress.")
            try:
                self.window.title("Dubbing Studio — working… (close hides, job keeps running)")
            except Exception:
                pass
            try:
                self.window.withdraw()
            except Exception:
                pass
            return
        try:
            if self.app is not None and isinstance(getattr(self.app, "settings", None), dict):
                current = self.app.settings.setdefault("dubbing", {})
                current.update({
                    "target_lang": self.target_lang.get(),
                    "separation_enabled": bool(self.separation.get()),
                    "phase_1b_enabled": bool(self.phase_1b.get()),
                })
                current.setdefault("whisper_model", str(DEFAULT_DUBBING_SETTINGS["whisper_model"]))
                current.setdefault("keep_bg_ratio", float(DEFAULT_DUBBING_SETTINGS["keep_bg_ratio"]))
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
        try:
            if getattr(self, "app", None) is not None and getattr(self.app, "dub_wizard", None) is self:
                self.app.dub_wizard = None
        except Exception:
            pass
