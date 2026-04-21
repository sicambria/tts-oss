from __future__ import annotations

import os
import queue
import re
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import numpy as np
os.environ.setdefault("FFMPEG_BINARY", imageio_ffmpeg.get_ffmpeg_exe())
warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
    category=RuntimeWarning,
)
from pydub import AudioSegment
from tkinter import END, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk


MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER = "Ana Florence"
ENGINE_AUTO = "Auto"
ENGINE_PIPER = "Piper"
ENGINE_XTTS = "XTTS v2"
PIPER_VOICE_DIR = Path.cwd() / "voices" / "piper"
PIPER_VOICE_OPTIONS = {
    "Hungarian | Anna | medium": {
        "code": "hu_HU-anna-medium",
        "xtts_language": "hu",
    },
    "English US | Lessac | medium": {
        "code": "en_US-lessac-medium",
        "xtts_language": "en",
    },
    "English GB | Alan | medium": {
        "code": "en_GB-alan-medium",
        "xtts_language": "en",
    },
}
DEFAULT_PIPER_VOICE_LABEL = "Hungarian | Anna | medium"
PAUSE_MS = 300
MAX_CHARS_PER_CHUNK = 280


def sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+|\n{2,}", text.strip(), flags=re.MULTILINE)
    return [part.strip() for part in parts if part.strip()]


def split_long_piece(piece: str, max_chars: int) -> list[str]:
    if len(piece) <= max_chars:
        return [piece]

    chunks: list[str] = []
    clauses = re.split(r"(?<=[,])\s+|(?<=\))\s+", piece)
    current = ""
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        candidate = f"{current} {clause}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = clause
        elif len(clause) > max_chars:
            words = clause.split()
            word_chunk = ""
            for word in words:
                word_candidate = f"{word_chunk} {word}".strip()
                if word_chunk and len(word_candidate) > max_chars:
                    chunks.append(word_chunk)
                    word_chunk = word
                else:
                    word_chunk = word_candidate
            if word_chunk:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(word_chunk)
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    sentences = sentence_split(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        for piece in split_long_piece(sentence, max_chars):
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


@dataclass
class SynthesisRequest:
    text: str
    language: str
    output_file: Path
    engine: str
    piper_voice_label: str
    speaker_name: str
    speaker_wav: str


def get_piper_voice_metadata(label: str) -> dict[str, str]:
    metadata = PIPER_VOICE_OPTIONS.get(label)
    if metadata is None:
        return PIPER_VOICE_OPTIONS[DEFAULT_PIPER_VOICE_LABEL]
    return metadata


def piper_model_path(voice_code: str) -> Path:
    return PIPER_VOICE_DIR / f"{voice_code}.onnx"


class XTTSService:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._tts = None
        self._sample_rate = 24000

    def ensure_loaded(self) -> None:
        if self._tts is not None:
            return
        self._log("Loading XTTS v2 model. First load can take a while.")
        try:
            import torch
            from TTS.api import TTS
        except Exception as exc:  # pragma: no cover - import path varies by machine
            raise RuntimeError(
                "Coqui TTS is not installed in this environment. Run .\\setup.ps1 first."
            ) from exc

        self._patch_torch_load(torch)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._log(f"Using device: {device}")
        self._tts = TTS(MODEL_NAME).to(device)
        sample_rate = getattr(self._tts.synthesizer, "output_sample_rate", None)
        if isinstance(sample_rate, int):
            self._sample_rate = sample_rate
        self._log("Model is ready.")

    @staticmethod
    def _patch_torch_load(torch_module) -> None:
        current = torch_module.load
        if getattr(current, "_coqui_xtts_patched", False):
            return

        def patched_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return current(*args, **kwargs)

        patched_load._coqui_xtts_patched = True
        torch_module.load = patched_load

    def synthesize(self, request: SynthesisRequest) -> Path:
        self.ensure_loaded()
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        chunks = chunk_text(request.text)
        if not chunks:
            raise ValueError("Text is empty after cleanup.")

        self._log(f"Prepared {len(chunks)} chunk(s) for synthesis.")
        combined = AudioSegment.silent(duration=0)

        kwargs = {"language": request.language}
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
            self._log("Voice source: reference WAV")
        else:
            kwargs["speaker"] = request.speaker_name or DEFAULT_SPEAKER
            self._log(f"Voice source: built-in speaker '{kwargs['speaker']}'")

        for index, chunk in enumerate(chunks, start=1):
            self._log(f"Synthesizing chunk {index}/{len(chunks)}")
            wav = self._tts.tts(text=chunk, split_sentences=True, **kwargs)
            array = np.asarray(wav, dtype=np.float32)
            pcm = np.int16(np.clip(array, -1.0, 1.0) * 32767).tobytes()
            segment = AudioSegment(
                data=pcm,
                sample_width=2,
                frame_rate=self._sample_rate,
                channels=1,
            )
            combined += segment
            if index < len(chunks):
                combined += AudioSegment.silent(duration=PAUSE_MS)

        request.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._log(f"Exporting MP3 to {request.output_file}")
        combined.export(
            request.output_file,
            format="mp3",
            bitrate="192k",
            parameters=["-ar", "44100"],
        )
        self._log("Finished.")
        return request.output_file


class PiperService:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._voices: dict[str, object] = {}

    def ensure_loaded(self, voice_code: str):
        voice = self._voices.get(voice_code)
        if voice is not None:
            return voice

        model_path = piper_model_path(voice_code)
        if not model_path.exists():
            raise RuntimeError(
                f"Piper voice '{voice_code}' is missing. Run .\\setup.ps1 to download it."
            )

        self._log(f"Loading Piper voice '{voice_code}'.")
        try:
            from piper.voice import PiperVoice
        except Exception as exc:
            raise RuntimeError(
                "Piper is not installed in this environment. Run .\\setup.ps1 first."
            ) from exc

        voice = PiperVoice.load(model_path, download_dir=PIPER_VOICE_DIR)
        self._voices[voice_code] = voice
        self._log("Piper voice is ready.")
        return voice

    def synthesize(self, request: SynthesisRequest) -> Path:
        voice_metadata = get_piper_voice_metadata(request.piper_voice_label)
        voice_code = voice_metadata["code"]
        voice = self.ensure_loaded(voice_code)
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        chunks = chunk_text(request.text)
        if not chunks:
            raise ValueError("Text is empty after cleanup.")

        self._log(f"Prepared {len(chunks)} chunk(s) for synthesis.")
        self._log(f"Voice source: Piper '{voice_code}'")
        combined = AudioSegment.silent(duration=0)

        for index, chunk in enumerate(chunks, start=1):
            self._log(f"Synthesizing chunk {index}/{len(chunks)}")
            for audio_chunk in voice.synthesize(chunk):
                segment = AudioSegment(
                    data=audio_chunk.audio_int16_bytes,
                    sample_width=audio_chunk.sample_width,
                    frame_rate=audio_chunk.sample_rate,
                    channels=audio_chunk.sample_channels,
                )
                combined += segment

            if index < len(chunks):
                combined += AudioSegment.silent(duration=PAUSE_MS)

        request.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._log(f"Exporting MP3 to {request.output_file}")
        combined.export(
            request.output_file,
            format="mp3",
            bitrate="192k",
            parameters=["-ar", "44100"],
        )
        self._log("Finished.")
        return request.output_file


class SynthesisCoordinator:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._xtts = XTTSService(log)
        self._piper = PiperService(log)

    @staticmethod
    def resolve_engine(request: SynthesisRequest) -> str:
        if request.engine == ENGINE_AUTO:
            return ENGINE_XTTS if request.speaker_wav else ENGINE_PIPER
        return request.engine

    def synthesize(self, request: SynthesisRequest) -> Path:
        resolved_engine = self.resolve_engine(request)
        if resolved_engine == ENGINE_PIPER:
            return self._piper.synthesize(request)
        return self._xtts.synthesize(request)


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Local TTS MP3 Generator")
        self.root.geometry("980x760")
        self.root.minsize(900, 650)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.service = SynthesisCoordinator(self.enqueue_log)
        self.worker: threading.Thread | None = None

        self.language = StringVar(value="hu")
        self.engine = StringVar(value=ENGINE_AUTO)
        self.piper_voice_label = StringVar(value=DEFAULT_PIPER_VOICE_LABEL)
        self.speaker_name = StringVar(value=DEFAULT_SPEAKER)
        self.speaker_wav = StringVar()
        self.output_file = StringVar(value=str((Path.cwd() / "output" / "speech.mp3").resolve()))
        self.status = StringVar(value="Ready")

        self._build_ui()
        self.language.trace_add("write", self.on_voice_settings_changed)
        self.engine.trace_add("write", self.on_voice_settings_changed)
        self.piper_voice_label.trace_add("write", self.on_voice_settings_changed)
        self.on_voice_settings_changed()
        self.root.after(150, self.flush_logs)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure("TFrame", padding=10)
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Subtle.TLabel", foreground="#4b5563")

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x")
        ttk.Label(header, text="Local TTS MP3 Generator", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Hungarian and English text to MP3 with Piper and XTTS",
            style="Subtle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        controls = ttk.LabelFrame(main, text="Options", padding=12)
        controls.pack(fill="x", pady=(12, 8))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Language").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        self.lang_box = ttk.Combobox(
            controls,
            textvariable=self.language,
            values=["hu", "en"],
            state="readonly",
            width=12,
        )
        self.lang_box.grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(controls, text="Engine").grid(row=0, column=2, sticky="w", padx=(18, 10), pady=6)
        self.engine_box = ttk.Combobox(
            controls,
            textvariable=self.engine,
            values=[ENGINE_AUTO, ENGINE_PIPER, ENGINE_XTTS],
            state="readonly",
            width=18,
        )
        self.engine_box.grid(row=0, column=3, sticky="w", pady=6)

        ttk.Label(controls, text="Built-in speaker").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=6
        )
        self.speaker_name_entry = ttk.Entry(controls, textvariable=self.speaker_name)
        self.speaker_name_entry.grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(controls, text="Piper voice").grid(
            row=1, column=2, sticky="w", padx=(18, 10), pady=6
        )
        self.piper_voice_box = ttk.Combobox(
            controls,
            textvariable=self.piper_voice_label,
            values=list(PIPER_VOICE_OPTIONS.keys()),
            state="readonly",
            width=28,
        )
        self.piper_voice_box.grid(row=1, column=3, columnspan=2, sticky="ew", pady=6)

        ttk.Label(controls, text="Reference WAV").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=6
        )
        self.speaker_wav_entry = ttk.Entry(controls, textvariable=self.speaker_wav)
        self.speaker_wav_entry.grid(row=2, column=1, columnspan=3, sticky="ew", pady=6)
        self.speaker_wav_button = ttk.Button(controls, text="Browse", command=self.pick_reference_wav)
        self.speaker_wav_button.grid(row=2, column=4, sticky="e", pady=6)

        ttk.Label(controls, text="Output MP3").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(controls, textvariable=self.output_file).grid(row=3, column=1, columnspan=3, sticky="ew", pady=6)
        ttk.Button(controls, text="Save As", command=self.pick_output_file).grid(row=3, column=4, sticky="e", pady=6)

        self.engine_hint = StringVar(value="")
        ttk.Label(controls, textvariable=self.engine_hint, style="Subtle.TLabel").grid(
            row=4, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Load .txt", command=self.load_text_file).pack(side="left")
        ttk.Button(actions, text="Generate MP3", command=self.start_generation).pack(side="right")

        ttk.Label(main, text="Text").pack(anchor="w")
        self.textbox = ttk.Frame(main)
        self.textbox.pack(fill="both", expand=True)

        self.text = Text(
            self.textbox,
            wrap="word",
            font=("Segoe UI", 11),
            padx=12,
            pady=12,
            undo=True,
        )
        self.text.pack(side="left", fill="both", expand=True)
        text_scroll = ttk.Scrollbar(self.textbox, orient="vertical", command=self.text.yview)
        text_scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=text_scroll.set)

        log_frame = ttk.LabelFrame(main, text="Status", padding=10)
        log_frame.pack(fill="both", expand=False, pady=(8, 0))
        ttk.Label(log_frame, textvariable=self.status).pack(anchor="w")
        self.log = Text(log_frame, height=10, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.configure(state="disabled")

    def resolved_engine(self) -> str:
        if self.engine.get() == ENGINE_AUTO:
            return ENGINE_XTTS if self.speaker_wav.get().strip() else ENGINE_PIPER
        return self.engine.get()

    def on_voice_settings_changed(self, *_args) -> None:
        selected_label = self.piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL
        voice_metadata = get_piper_voice_metadata(selected_label)

        resolved = self.resolved_engine()
        xtts_enabled = resolved == ENGINE_XTTS
        piper_enabled = resolved == ENGINE_PIPER

        state = "normal" if xtts_enabled else "disabled"
        self.speaker_name_entry.configure(state=state)
        self.speaker_wav_entry.configure(state=state)
        self.speaker_wav_button.configure(state=state)
        self.piper_voice_box.configure(state="readonly" if piper_enabled or self.engine.get() == ENGINE_AUTO else "disabled")

        if resolved == ENGINE_PIPER:
            self.engine_hint.set(
                f"Piper uses the local '{voice_metadata['code']}' voice. Adding a reference WAV switches Auto to XTTS."
            )
        else:
            self.engine_hint.set(
                "XTTS uses the Language field plus built-in speakers or reference voice cloning. Piper voice selection is ignored."
            )

    def enqueue_log(self, message: str) -> None:
        self.log_queue.put(message)

    def flush_logs(self) -> None:
        while not self.log_queue.empty():
            line = self.log_queue.get_nowait()
            self.status.set(line)
            self.log.configure(state="normal")
            self.log.insert(END, f"{line}\n")
            self.log.see(END)
            self.log.configure(state="disabled")
        self.root.after(150, self.flush_logs)

    def pick_reference_wav(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose reference voice WAV",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac"), ("All files", "*.*")],
        )
        if path:
            self.speaker_wav.set(path)

    def pick_output_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save output MP3",
            defaultextension=".mp3",
            filetypes=[("MP3 files", "*.mp3")],
            initialfile="speech.mp3",
        )
        if path:
            self.output_file.set(path)

    def load_text_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open text file",
            filetypes=[("Text files", "*.txt *.md"), ("All files", "*.*")],
        )
        if not path:
            return
        content = Path(path).read_text(encoding="utf-8")
        self.text.delete("1.0", END)
        self.text.insert("1.0", content)
        self.enqueue_log(f"Loaded text from {path}")

    def collect_request(self) -> SynthesisRequest | None:
        text = self.text.get("1.0", END).strip()
        if not text:
            messagebox.showerror("Missing text", "Paste or load some text first.")
            return None

        output = self.output_file.get().strip()
        if not output:
            messagebox.showerror("Missing output", "Choose an output MP3 file.")
            return None

        speaker_wav = self.speaker_wav.get().strip()
        if speaker_wav and not Path(speaker_wav).exists():
            messagebox.showerror("Missing file", "The selected reference voice file does not exist.")
            return None

        return SynthesisRequest(
            text=text,
            language=self.language.get().strip() or "hu",
            output_file=Path(output),
            engine=self.engine.get().strip() or ENGINE_AUTO,
            piper_voice_label=self.piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL,
            speaker_name=self.speaker_name.get().strip() or DEFAULT_SPEAKER,
            speaker_wav=speaker_wav,
        )

    def start_generation(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Generation is already running.")
            return

        request = self.collect_request()
        if request is None:
            return

        if self.service.resolve_engine(request) == ENGINE_XTTS and not self.ensure_xtts_license_acceptance():
            return

        self.enqueue_log("Starting synthesis job.")
        self.worker = threading.Thread(target=self.run_generation, args=(request,), daemon=True)
        self.worker.start()

    def ensure_xtts_license_acceptance(self) -> bool:
        if os.environ.get("COQUI_TOS_AGREED") == "1":
            return True

        accepted = messagebox.askyesno(
            "XTTS License Confirmation",
            (
                "XTTS v2 requires you to confirm Coqui's license terms on first download.\n\n"
                "Select Yes only if either:\n"
                "- you purchased a commercial license from Coqui, or\n"
                "- you agree to the non-commercial CPML terms at https://coqui.ai/cpml\n\n"
                "Continue?"
            ),
        )
        if accepted:
            os.environ["COQUI_TOS_AGREED"] = "1"
            return True
        self.enqueue_log("XTTS license confirmation was declined.")
        return False

    def run_generation(self, request: SynthesisRequest) -> None:
        try:
            result = self.service.synthesize(request)
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")
            self.root.after(0, lambda: messagebox.showerror("Generation failed", str(exc)))
            return

        self.enqueue_log(f"Saved MP3: {result}")
        self.root.after(
            0,
            lambda: messagebox.showinfo("Done", f"MP3 created:\n{result}"),
        )


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
