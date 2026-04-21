from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

import imageio_ffmpeg
import numpy as np
os.environ.setdefault("FFMPEG_BINARY", imageio_ffmpeg.get_ffmpeg_exe())
warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
    category=RuntimeWarning,
)
from pydub import AudioSegment
from tkinter import BooleanVar, END, StringVar, Text, Tk, Toplevel, filedialog, messagebox
from tkinter import ttk


MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER = "Ana Florence"
ENGINE_AUTO = "Auto"
ENGINE_PIPER = "Piper"
ENGINE_XTTS = "XTTS v2"
PIPER_VOICE_DIR = Path.cwd() / "voices" / "piper"
APP_SETTINGS_PATH = Path.cwd() / "settings.json"
PIPER_VOICES_JSON_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
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
PREVIEW_OUTPUT_PATH = Path.cwd() / "output" / "read-aloud-preview.mp3"
PAUSE_MS = 300
MAX_CHARS_PER_CHUNK = 280
READ_ALOUD_LINE_TAG = "read_aloud_line"
SUPPORTED_OUTPUT_FORMATS = {
    ".mp3": "MP3",
    ".ogg": "OGG",
    ".wav": "WAV",
}
PREVIEW_FILE_GLOB = "read-aloud-preview-*.wav"
SURFACE_BG = "#f4f6fb"
CARD_BG = "#ffffff"
ACCENT = "#2563eb"
ACCENT_ACTIVE = "#1d4ed8"
MUTED_TEXT = "#52607a"
TEXT_BG = "#fbfcfe"
TEXT_BORDER = "#d7deea"


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
class TextChunk:
    text: str
    start: int
    end: int


def find_word_start_offset(text: str, offset: int) -> int | None:
    clamped = max(0, min(offset, len(text)))
    for match in re.finditer(r"\S+", text):
        if match.start() <= clamped < match.end():
            return match.start()
        if match.start() > clamped:
            return match.start()
    return None


def chunk_text_with_offsets(
    text: str,
    max_chars: int = MAX_CHARS_PER_CHUNK,
    start_offset: int = 0,
) -> list[TextChunk]:
    matches = list(re.finditer(r"\S+", text))
    if not matches:
        return []

    effective_start = find_word_start_offset(text, start_offset)
    if effective_start is None:
        return []

    start_index = 0
    for index, match in enumerate(matches):
        if match.start() >= effective_start:
            start_index = index
            break

    chunks: list[TextChunk] = []
    chunk_start = matches[start_index].start()
    chunk_end = matches[start_index].end()

    for match in matches[start_index + 1:]:
        candidate = text[chunk_start:match.end()].strip()
        if candidate and len(candidate) > max_chars:
            chunk_text_value = text[chunk_start:chunk_end].strip()
            if chunk_text_value:
                chunks.append(TextChunk(text=chunk_text_value, start=chunk_start, end=chunk_end))
            chunk_start = match.start()
        chunk_end = match.end()

    chunk_text_value = text[chunk_start:chunk_end].strip()
    if chunk_text_value:
        chunks.append(TextChunk(text=chunk_text_value, start=chunk_start, end=chunk_end))
    return chunks


def output_format_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_OUTPUT_FORMATS:
        allowed = ", ".join(SUPPORTED_OUTPUT_FORMATS)
        raise ValueError(f"Unsupported output format '{suffix or '(none)'}'. Choose one of: {allowed}.")
    return suffix[1:]


def export_audio_segment(audio: AudioSegment, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_format = output_format_for_path(output_file)
    export_kwargs: dict[str, object] = {"format": output_format}

    if output_format in {"mp3", "ogg"}:
        export_kwargs["bitrate"] = "192k"
        export_kwargs["parameters"] = ["-ar", "44100"]
    else:
        export_kwargs["parameters"] = ["-ar", "44100"]

    audio.export(output_file, **export_kwargs)


@dataclass
class SynthesisRequest:
    text: str
    language: str
    output_file: Path
    engine: str
    piper_voice_label: str
    piper_voice_code: str
    speaker_name: str
    speaker_wav: str


def get_piper_voice_metadata(label: str) -> dict[str, str]:
    metadata = PIPER_VOICE_OPTIONS.get(label)
    if metadata is None:
        return PIPER_VOICE_OPTIONS[DEFAULT_PIPER_VOICE_LABEL]
    return metadata


def label_for_piper_voice(voice_code: str, voice_info: dict | None = None) -> str:
    if voice_info is not None:
        language = voice_info.get("language", {})
        language_name = language.get("name_english", voice_code.split("-")[0])
        country_name = language.get("country_english", "")
        region = f" {country_name}" if country_name else ""
        voice_name = str(voice_info.get("name", "")).replace("_", " ").title()
        quality = voice_info.get("quality", "")
        return f"{language_name}{region} | {voice_name} | {quality}"

    parts = voice_code.split("-")
    lang_code = parts[0]
    name = parts[1] if len(parts) > 1 else "voice"
    quality = parts[2] if len(parts) > 2 else "unknown"
    language_map = {
        "hu_HU": "Hungarian",
        "en_US": "English United States",
        "en_GB": "English Great Britain",
    }
    language_name = language_map.get(lang_code, lang_code)
    return f"{language_name} | {name.replace('_', ' ').title()} | {quality}"


def load_app_settings() -> dict:
    if not APP_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_app_settings(settings: dict) -> None:
    APP_SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def discover_local_piper_voices() -> dict[str, dict[str, str]]:
    options = dict(PIPER_VOICE_OPTIONS)
    if not PIPER_VOICE_DIR.exists():
        return options

    for model_path in sorted(PIPER_VOICE_DIR.glob("*.onnx")):
        config_path = model_path.with_suffix(".onnx.json")
        if not config_path.exists():
            continue

        voice_code = model_path.stem
        if any(metadata["code"] == voice_code for metadata in options.values()):
            continue
        label = label_for_piper_voice(voice_code)
        language_prefix = voice_code.split("-")[0]
        xtts_language = "hu" if language_prefix == "hu_HU" else "en"
        options.setdefault(
            label,
            {
                "code": voice_code,
                "xtts_language": xtts_language,
            },
        )

    return dict(sorted(options.items()))


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
                "Coqui TTS is not installed in this environment. Run the setup script first (`.\\setup.ps1` on Windows or `./setup.sh` on Linux/macOS)."
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

    def iter_segments(self, request: SynthesisRequest, start_offset: int = 0):
        self.ensure_loaded()
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        chunks = chunk_text_with_offsets(request.text, start_offset=start_offset)
        if not chunks:
            raise ValueError("Text is empty after cleanup.")

        self._log(f"Prepared {len(chunks)} chunk(s) for synthesis.")

        kwargs = {"language": request.language}
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
            self._log("Voice source: reference WAV")
        else:
            kwargs["speaker"] = request.speaker_name or DEFAULT_SPEAKER
            self._log(f"Voice source: built-in speaker '{kwargs['speaker']}'")

        for index, chunk in enumerate(chunks, start=1):
            self._log(f"Synthesizing chunk {index}/{len(chunks)}")
            wav = self._tts.tts(text=chunk.text, split_sentences=True, **kwargs)
            array = np.asarray(wav, dtype=np.float32)
            pcm = np.int16(np.clip(array, -1.0, 1.0) * 32767).tobytes()
            segment = AudioSegment(
                data=pcm,
                sample_width=2,
                frame_rate=self._sample_rate,
                channels=1,
            )
            yield chunk, segment

    def synthesize(self, request: SynthesisRequest) -> Path:
        chunks = list(self.iter_segments(request))
        combined = AudioSegment.silent(duration=0)
        for index, (_chunk, segment) in enumerate(chunks, start=1):
            combined += segment
            if index < len(chunks):
                combined += AudioSegment.silent(duration=PAUSE_MS)

        self._log(f"Exporting audio to {request.output_file}")
        export_audio_segment(combined, request.output_file)
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
                f"Piper voice '{voice_code}' is missing. Run the setup script to download it (`.\\setup.ps1` on Windows or `./setup.sh` on Linux/macOS)."
            )

        self._log(f"Loading Piper voice '{voice_code}'.")
        try:
            from piper.voice import PiperVoice
        except Exception as exc:
            raise RuntimeError(
                "Piper is not installed in this environment. Run the setup script first (`.\\setup.ps1` on Windows or `./setup.sh` on Linux/macOS)."
            ) from exc

        voice = PiperVoice.load(model_path, download_dir=PIPER_VOICE_DIR)
        self._voices[voice_code] = voice
        self._log("Piper voice is ready.")
        return voice

    def iter_segments(self, request: SynthesisRequest, start_offset: int = 0):
        voice_code = request.piper_voice_code
        voice = self.ensure_loaded(voice_code)
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        chunks = chunk_text_with_offsets(request.text, start_offset=start_offset)
        if not chunks:
            raise ValueError("Text is empty after cleanup.")

        self._log(f"Prepared {len(chunks)} chunk(s) for synthesis.")
        self._log(f"Voice source: Piper '{voice_code}'")

        for index, chunk in enumerate(chunks, start=1):
            self._log(f"Synthesizing chunk {index}/{len(chunks)}")
            segment = AudioSegment.silent(duration=0)
            for audio_chunk in voice.synthesize(chunk.text):
                segment += AudioSegment(
                    data=audio_chunk.audio_int16_bytes,
                    sample_width=audio_chunk.sample_width,
                    frame_rate=audio_chunk.sample_rate,
                    channels=audio_chunk.sample_channels,
                )
            yield chunk, segment

    def synthesize(self, request: SynthesisRequest) -> Path:
        chunks = list(self.iter_segments(request))
        combined = AudioSegment.silent(duration=0)
        for index, (_chunk, segment) in enumerate(chunks, start=1):
            combined += segment
            if index < len(chunks):
                combined += AudioSegment.silent(duration=PAUSE_MS)

        self._log(f"Exporting audio to {request.output_file}")
        export_audio_segment(combined, request.output_file)
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

    def iter_segments(self, request: SynthesisRequest, start_offset: int = 0):
        resolved_engine = self.resolve_engine(request)
        if resolved_engine == ENGINE_PIPER:
            yield from self._piper.iter_segments(request, start_offset=start_offset)
            return
        yield from self._xtts.iter_segments(request, start_offset=start_offset)


class AudioPlayer:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._ready = False
        self._paused = False
        self._active = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        try:
            import pygame
        except Exception as exc:
            raise RuntimeError(
                "pygame is not installed. Run the setup script first (`.\\setup.ps1` on Windows or `./setup.sh` on Linux/macOS)."
            ) from exc

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self._ready = True

    def play(self, path: Path) -> None:
        self.ensure_ready()
        import pygame

        self._paused = False
        self._active = True
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play()
        self._log(f"Playing audio: {path.name}")

    def play_blocking(self, path: Path, stop_event: threading.Event) -> None:
        self.play(path)
        import pygame

        try:
            while True:
                if stop_event.is_set():
                    pygame.mixer.music.stop()
                    return
                if self._paused:
                    time.sleep(0.05)
                    continue
                if not pygame.mixer.music.get_busy():
                    return
                time.sleep(0.05)
        finally:
            self._paused = False
            self._active = False

    def pause(self) -> None:
        if not self._active:
            return
        self.ensure_ready()
        import pygame

        pygame.mixer.music.pause()
        self._paused = True
        self._log("Playback paused.")

    def resume(self) -> None:
        if not self._active:
            return
        self.ensure_ready()
        import pygame

        pygame.mixer.music.unpause()
        self._paused = False
        self._log("Playback resumed.")

    def stop(self, quiet: bool = False) -> None:
        if not self._ready:
            return
        import pygame

        was_active = self._active
        pygame.mixer.music.stop()
        self._paused = False
        self._active = False
        if was_active and not quiet:
            self._log("Playback stopped.")

    def is_active(self) -> bool:
        return self._active

    def is_paused(self) -> bool:
        return self._paused


class PiperVoiceWizard:
    def __init__(self, app: "App") -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.title("Piper Voice Wizard")
        self.window.geometry("980x620")
        self.window.minsize(900, 560)

        self.search = StringVar()
        self.quality = StringVar(value="all")
        self.installed_only = BooleanVar(value=False)
        self.status = StringVar(value="Loading Piper voice catalog...")

        self.catalog: dict[str, dict] = {}
        self.filtered_codes: list[str] = []
        self.downloading = False

        self._build_ui()
        self.search.trace_add("write", self.apply_filters)
        self.quality.trace_add("write", self.apply_filters)
        self.installed_only.trace_add("write", self.apply_filters)
        threading.Thread(target=self.load_catalog, daemon=True).start()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Search").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.search).grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(controls, text="Quality").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.quality,
            values=["all", "x_low", "low", "medium", "high"],
            state="readonly",
            width=10,
        ).grid(row=0, column=3, sticky="w", padx=(8, 12))
        ttk.Checkbutton(controls, text="Installed only", variable=self.installed_only).grid(row=0, column=4, sticky="w")

        columns = ("label", "code", "quality", "installed")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        self.tree.heading("label", text="Voice")
        self.tree.heading("code", text="Code")
        self.tree.heading("quality", text="Quality")
        self.tree.heading("installed", text="Installed")
        self.tree.column("label", width=360)
        self.tree.column("code", width=220)
        self.tree.column("quality", width=90, anchor="center")
        self.tree.column("installed", width=90, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(12, 0))
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="↻ Refresh Catalog", command=self.refresh_catalog).pack(side="left")
        ttk.Button(actions, text="⬇ Download Selected", style="Accent.TButton", command=self.download_selected).pack(side="right")
        ttk.Button(actions, text="★ Set As Default", command=self.set_selected_default).pack(side="right", padx=(0, 8))

        ttk.Label(frame, textvariable=self.status).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def refresh_catalog(self) -> None:
        if self.downloading:
            return
        self.status.set("Refreshing Piper voice catalog...")
        threading.Thread(target=self.load_catalog, daemon=True).start()

    def load_catalog(self) -> None:
        try:
            with urlopen(PIPER_VOICES_JSON_URL) as response:
                catalog = json.load(response)
        except Exception as exc:
            error_message = f"Failed to load Piper catalog: {exc}"
            self.window.after(0, lambda message=error_message: self.status.set(message))
            return

        self.catalog = catalog
        self.window.after(0, self.apply_filters)

    def installed_codes(self) -> set[str]:
        return {
            model_path.stem
            for model_path in PIPER_VOICE_DIR.glob("*.onnx")
            if model_path.with_suffix(".onnx.json").exists()
        } if PIPER_VOICE_DIR.exists() else set()

    def apply_filters(self, *_args) -> None:
        installed_codes = self.installed_codes()
        search_text = self.search.get().strip().lower()
        quality = self.quality.get().strip()

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.filtered_codes = []
        for voice_code in sorted(self.catalog):
            info = self.catalog[voice_code]
            label = label_for_piper_voice(voice_code, info)
            haystack = f"{label} {voice_code}".lower()
            is_installed = voice_code in installed_codes

            if search_text and search_text not in haystack:
                continue
            if quality != "all" and info.get("quality") != quality:
                continue
            if self.installed_only.get() and not is_installed:
                continue

            self.filtered_codes.append(voice_code)
            self.tree.insert(
                "",
                "end",
                iid=voice_code,
                values=(label, voice_code, info.get("quality", ""), "Yes" if is_installed else "No"),
            )

        self.status.set(f"{len(self.filtered_codes)} voice(s) shown.")

    def selected_voice_code(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a Piper voice first.")
            return None
        return selection[0]

    def download_selected(self) -> None:
        voice_code = self.selected_voice_code()
        if not voice_code or self.downloading:
            return

        self.downloading = True
        self.status.set(f"Downloading {voice_code}...")
        threading.Thread(target=self._download_voice_worker, args=(voice_code,), daemon=True).start()

    def _download_voice_worker(self, voice_code: str) -> None:
        try:
            from piper.download_voices import download_voice

            PIPER_VOICE_DIR.mkdir(parents=True, exist_ok=True)
            download_voice(voice_code, PIPER_VOICE_DIR)
        except Exception as exc:
            error_message = f"Download failed: {exc}"
            self.window.after(0, lambda message=error_message: self.status.set(message))
        else:
            def on_done() -> None:
                self.status.set(f"Downloaded {voice_code}.")
                self.app.reload_piper_voices(preferred_code=voice_code)
                self.apply_filters()
            self.window.after(0, on_done)
        finally:
            self.downloading = False

    def set_selected_default(self) -> None:
        voice_code = self.selected_voice_code()
        if not voice_code:
            return

        label = self.app.find_piper_label_by_code(voice_code)
        if label is None:
            messagebox.showinfo("Voice not available", "Download the voice first, then set it as default.")
            return

        self.app.set_default_piper_voice(label)
        self.status.set(f"Default Piper voice set to {voice_code}.")


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Local TTS Audio Generator")
        self.root.geometry("980x760")
        self.root.minsize(900, 650)
        self.root.configure(bg=SURFACE_BG)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.service = SynthesisCoordinator(self.enqueue_log)
        self.worker: threading.Thread | None = None
        self.preview_worker: threading.Thread | None = None
        self.preview_stop_event = threading.Event()
        self.preview_job_id = 0
        self.last_selection_start_offset: int | None = None
        self.player = AudioPlayer(self.enqueue_log)
        self.settings = load_app_settings()
        self.voice_wizard: PiperVoiceWizard | None = None
        self.piper_voice_options = discover_local_piper_voices()

        self.language = StringVar(value="hu")
        self.engine = StringVar(value=ENGINE_AUTO)
        initial_piper_voice = self.settings.get("default_piper_voice_label", DEFAULT_PIPER_VOICE_LABEL)
        if initial_piper_voice not in self.piper_voice_options:
            initial_piper_voice = DEFAULT_PIPER_VOICE_LABEL
        self.piper_voice_label = StringVar(value=initial_piper_voice)
        self.speaker_name = StringVar(value=DEFAULT_SPEAKER)
        self.speaker_wav = StringVar()
        self.output_file = StringVar(value=str((Path.cwd() / "output" / "speech.mp3").resolve()))
        self.status = StringVar(value="Ready")
        self.playback_toggle_label = StringVar(value="⏸ Pause")
        self.generation_modal: Toplevel | None = None
        self.generation_progress = None
        self.generation_status = StringVar(value="")
        self.generation_result_path: Path | None = None
        self.generation_close_button = None
        self.generation_open_file_button = None
        self.generation_open_folder_button = None

        self._build_ui()
        self.language.trace_add("write", self.on_voice_settings_changed)
        self.engine.trace_add("write", self.on_voice_settings_changed)
        self.piper_voice_label.trace_add("write", self.on_voice_settings_changed)
        self.on_voice_settings_changed()
        self.root.after(150, self.flush_logs)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background=SURFACE_BG)
        style.configure("HeaderPanel.TFrame", background=CARD_BG)
        style.configure("Toolbar.TFrame", background=SURFACE_BG)
        style.configure("TLabel", background=SURFACE_BG)
        style.configure("Header.TLabel", background=CARD_BG, foreground="#101828", font=("Segoe UI Semibold", 20))
        style.configure("HeroIcon.TLabel", background=CARD_BG, foreground=ACCENT, font=("Segoe UI Symbol", 22))
        style.configure("Subtle.TLabel", background=CARD_BG, foreground=MUTED_TEXT, font=("Segoe UI", 10))
        style.configure("Hint.TLabel", background=SURFACE_BG, foreground=MUTED_TEXT, font=("Segoe UI", 9))
        style.configure(
            "TLabelframe",
            background=CARD_BG,
            bordercolor=TEXT_BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=CARD_BG, foreground="#0f172a", font=("Segoe UI Semibold", 10))
        style.configure(
            "TButton",
            padding=(12, 8),
            font=("Segoe UI Semibold", 9),
            background=CARD_BG,
            foreground="#0f172a",
            bordercolor=TEXT_BORDER,
            focusthickness=0,
        )
        style.map("TButton", background=[("active", "#eef2ff")], bordercolor=[("active", ACCENT)])
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            bordercolor=ACCENT,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_ACTIVE)],
            bordercolor=[("active", ACCENT_ACTIVE)],
            foreground=[("active", "#ffffff")],
        )
        style.configure("TEntry", fieldbackground=CARD_BG, bordercolor=TEXT_BORDER, padding=6)
        style.configure("TCombobox", fieldbackground=CARD_BG, bordercolor=TEXT_BORDER, padding=6)

    def _build_ui(self) -> None:
        self._configure_styles()

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main, style="HeaderPanel.TFrame", padding=16)
        header.pack(fill="x", pady=(0, 12))
        brand = ttk.Frame(header, style="HeaderPanel.TFrame")
        brand.pack(fill="x")
        ttk.Label(brand, text="♪", style="HeroIcon.TLabel").pack(side="left", padx=(0, 10))
        header_text = ttk.Frame(brand, style="HeaderPanel.TFrame")
        header_text.pack(side="left", fill="x", expand=True)
        ttk.Label(header_text, text="Local TTS Audio Generator", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header_text,
            text="Local Piper and XTTS voices for many languages, with MP3, OGG, and WAV export.",
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
            values=list(self.piper_voice_options.keys()),
            state="readonly",
            width=28,
        )
        self.piper_voice_box.grid(row=1, column=3, columnspan=2, sticky="ew", pady=6)

        ttk.Label(controls, text="Reference WAV").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=6
        )
        self.speaker_wav_entry = ttk.Entry(controls, textvariable=self.speaker_wav)
        self.speaker_wav_entry.grid(row=2, column=1, columnspan=3, sticky="ew", pady=6)
        self.speaker_wav_button = ttk.Button(controls, text="📁 Browse", command=self.pick_reference_wav)
        self.speaker_wav_button.grid(row=2, column=4, sticky="e", pady=6)

        ttk.Label(controls, text="Output file").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(controls, textvariable=self.output_file).grid(row=3, column=1, columnspan=3, sticky="ew", pady=6)
        ttk.Button(controls, text="🗂 Save As", command=self.pick_output_file).grid(row=3, column=4, sticky="e", pady=6)

        self.engine_hint = StringVar(value="")
        ttk.Label(controls, textvariable=self.engine_hint, style="Hint.TLabel").grid(
            row=4, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

        actions = ttk.Frame(main, style="Toolbar.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="📄 Load Text", command=self.load_text_file).pack(side="left")
        ttk.Button(actions, text="🎙 Voice Wizard", command=self.open_voice_wizard).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="▶ Read Aloud", style="Accent.TButton", command=self.start_read_aloud).pack(side="left", padx=(8, 0))
        self.playback_toggle_button = ttk.Button(
            actions,
            textvariable=self.playback_toggle_label,
            command=self.toggle_playback_pause,
        )
        self.playback_toggle_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="⏹ Stop", command=self.stop_playback).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="💾 Generate Audio", style="Accent.TButton", command=self.start_generation).pack(side="right")

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
            exportselection=False,
            bg=TEXT_BG,
            fg="#0f172a",
            relief="flat",
            insertbackground=ACCENT,
            highlightthickness=1,
            highlightbackground=TEXT_BORDER,
            highlightcolor=ACCENT,
        )
        self.text.pack(side="left", fill="both", expand=True)
        text_scroll = ttk.Scrollbar(self.textbox, orient="vertical", command=self.text.yview)
        text_scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=text_scroll.set)
        self.text.tag_configure(READ_ALOUD_LINE_TAG, background="#fff3bf")
        self.text.bind("<ButtonRelease-1>", self.on_text_click)
        self.text.bind("<ButtonRelease-1>", self.update_selection_cache, add="+")
        self.text.bind("<KeyRelease>", self.update_selection_cache, add="+")

        log_frame = ttk.LabelFrame(main, text="Status", padding=10)
        log_frame.pack(fill="both", expand=False, pady=(8, 0))
        ttk.Label(log_frame, textvariable=self.status).pack(anchor="w")
        self.log = Text(
            log_frame,
            height=10,
            wrap="word",
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#dbe4ff",
            relief="flat",
            insertbackground="#dbe4ff",
        )
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.configure(state="disabled")

    def resolved_engine(self) -> str:
        if self.engine.get() == ENGINE_AUTO:
            return ENGINE_XTTS if self.speaker_wav.get().strip() else ENGINE_PIPER
        return self.engine.get()

    def reload_piper_voices(self, preferred_code: str | None = None) -> None:
        self.piper_voice_options = discover_local_piper_voices()
        labels = list(self.piper_voice_options.keys())
        self.piper_voice_box.configure(values=labels)

        preferred_label = self.piper_voice_label.get()
        if preferred_code is not None:
            preferred_label = self.find_piper_label_by_code(preferred_code) or preferred_label
        if preferred_label not in self.piper_voice_options:
            preferred_label = DEFAULT_PIPER_VOICE_LABEL
        self.piper_voice_label.set(preferred_label)

    def find_piper_label_by_code(self, voice_code: str) -> str | None:
        for label, metadata in self.piper_voice_options.items():
            if metadata["code"] == voice_code:
                return label
        return None

    def set_default_piper_voice(self, label: str) -> None:
        self.settings["default_piper_voice_label"] = label
        save_app_settings(self.settings)
        self.piper_voice_label.set(label)

    def on_voice_settings_changed(self, *_args) -> None:
        selected_label = self.piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL
        voice_metadata = self.piper_voice_options.get(selected_label) or get_piper_voice_metadata(selected_label)

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
            title="Save output audio",
            defaultextension=".mp3",
            filetypes=[
                ("Audio files", "*.mp3 *.ogg *.wav"),
                ("MP3 files", "*.mp3"),
                ("OGG files", "*.ogg"),
                ("WAV files", "*.wav"),
            ],
            initialfile="speech.mp3",
        )
        if path:
            self.output_file.set(path)

    def open_voice_wizard(self) -> None:
        if self.voice_wizard is not None and self.voice_wizard.window.winfo_exists():
            self.voice_wizard.window.lift()
            self.voice_wizard.window.focus_force()
            return
        self.voice_wizard = PiperVoiceWizard(self)

    def open_path_in_system(self, path: Path) -> None:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    def show_generation_modal(self, output_path: Path) -> None:
        if self.generation_modal is not None and self.generation_modal.winfo_exists():
            self.generation_modal.destroy()

        self.generation_result_path = output_path
        self.generation_modal = Toplevel(self.root)
        self.generation_modal.title("Generating Audio")
        self.generation_modal.transient(self.root)
        self.generation_modal.geometry("520x220")
        self.generation_modal.resizable(False, False)
        self.generation_modal.grab_set()
        self.generation_modal.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(self.generation_modal, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Creating audio file", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=f"Output: {output_path}",
            style="Hint.TLabel",
            wraplength=480,
        ).pack(anchor="w", pady=(6, 10))

        self.generation_status.set("Preparing synthesis...")
        ttk.Label(frame, textvariable=self.generation_status).pack(anchor="w")

        self.generation_progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=100)
        self.generation_progress.pack(fill="x", pady=(10, 12))
        self.generation_progress["value"] = 0

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom", pady=(8, 0))
        self.generation_close_button = ttk.Button(buttons, text="Close", command=self.close_generation_modal, state="disabled")
        self.generation_close_button.pack(side="right")
        self.generation_open_folder_button = ttk.Button(
            buttons,
            text="Open Folder",
            command=self.open_generated_folder,
            state="disabled",
        )
        self.generation_open_folder_button.pack(side="right", padx=(0, 8))
        self.generation_open_file_button = ttk.Button(
            buttons,
            text="Open File",
            command=self.open_generated_file,
            state="disabled",
        )
        self.generation_open_file_button.pack(side="right", padx=(0, 8))

        self.generation_modal.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - self.generation_modal.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - self.generation_modal.winfo_height()) // 2)
        self.generation_modal.geometry(f"+{x}+{y}")

    def close_generation_modal(self) -> None:
        if self.generation_modal is not None and self.generation_modal.winfo_exists():
            self.generation_modal.grab_release()
            self.generation_modal.destroy()
        self.generation_modal = None

    def update_generation_progress(self, current: int, total: int, message: str) -> None:
        if self.generation_modal is None or not self.generation_modal.winfo_exists() or self.generation_progress is None:
            return

        progress = 10 if total <= 0 else min(95, max(10, round((current / total) * 90)))
        self.generation_progress["value"] = progress
        self.generation_status.set(message)

    def finish_generation_modal(self, result: Path | None, error: str | None = None) -> None:
        if self.generation_modal is None or not self.generation_modal.winfo_exists() or self.generation_progress is None:
            return

        if error is None and result is not None:
            self.generation_progress["value"] = 100
            self.generation_status.set(f"Audio created: {result}")
            self.generation_result_path = result
            self.generation_modal.protocol("WM_DELETE_WINDOW", self.close_generation_modal)
            self.generation_close_button.configure(state="normal")
            self.generation_open_file_button.configure(state="normal")
            self.generation_open_folder_button.configure(state="normal")
        else:
            self.generation_progress["value"] = 0
            self.generation_status.set(f"Generation failed: {error}")
            self.generation_result_path = None
            self.generation_modal.protocol("WM_DELETE_WINDOW", self.close_generation_modal)
            self.generation_close_button.configure(state="normal")
            self.generation_open_file_button.configure(state="disabled")
            self.generation_open_folder_button.configure(state="disabled")

    def open_generated_file(self) -> None:
        if self.generation_result_path is None:
            return
        self.open_path_in_system(self.generation_result_path)

    def open_generated_folder(self) -> None:
        target = self.generation_result_path.parent if self.generation_result_path is not None else Path.cwd()
        self.open_path_in_system(target)

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
        self.last_selection_start_offset = None
        self.clear_read_aloud_highlight()
        self.enqueue_log(f"Loaded text from {path}")

    def collect_request(self, require_output: bool = True) -> SynthesisRequest | None:
        text = self.get_text_content()
        if not text.strip():
            messagebox.showerror("Missing text", "Paste or load some text first.")
            return None

        output = self.output_file.get().strip()
        if require_output:
            if not output:
                messagebox.showerror("Missing output", "Choose an output audio file.")
                return None
            try:
                output_format_for_path(Path(output))
            except ValueError as exc:
                messagebox.showerror("Invalid output format", str(exc))
                return None

        speaker_wav = self.speaker_wav.get().strip()
        if speaker_wav and not Path(speaker_wav).exists():
            messagebox.showerror("Missing file", "The selected reference voice file does not exist.")
            return None

        return SynthesisRequest(
            text=text,
            language=self.language.get().strip() or "hu",
            output_file=Path(output or PREVIEW_OUTPUT_PATH),
            engine=self.engine.get().strip() or ENGINE_AUTO,
            piper_voice_label=self.piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL,
            piper_voice_code=(self.piper_voice_options.get(
                self.piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL,
                get_piper_voice_metadata(DEFAULT_PIPER_VOICE_LABEL),
            )["code"]),
            speaker_name=self.speaker_name.get().strip() or DEFAULT_SPEAKER,
            speaker_wav=speaker_wav,
        )

    def start_generation(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Generation is already running.")
            return

        request = self.collect_request(require_output=True)
        if request is None:
            return

        if self.service.resolve_engine(request) == ENGINE_XTTS and not self.ensure_xtts_license_acceptance():
            return

        self.enqueue_log("Starting synthesis job.")
        self.show_generation_modal(request.output_file)
        self.worker = threading.Thread(target=self.run_generation, args=(request,), daemon=True)
        self.worker.start()

    def start_read_aloud(self) -> None:
        self.start_read_aloud_from(None, reason="button")

    def start_read_aloud_from(self, start_offset: int | None, reason: str = "button") -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Audio generation is already running.")
            return

        request = self.collect_request(require_output=False)
        if request is None:
            return

        resolved_start_offset = start_offset
        if resolved_start_offset is None:
            resolved_start_offset = self.get_read_aloud_start_offset()
        if resolved_start_offset is None:
            messagebox.showinfo("No speech content", "Enter some text first.")
            return

        if self.service.resolve_engine(request) == ENGINE_XTTS and not self.ensure_xtts_license_acceptance():
            return

        self.preview_job_id += 1
        self.preview_stop_event.set()
        self.player.stop(quiet=True)
        self.cleanup_preview_files()
        self.preview_stop_event = threading.Event()
        job_id = self.preview_job_id
        if reason == "click_jump":
            self.enqueue_log("Jumping read aloud to clicked word.")
        elif self.text.tag_ranges("sel") or self.last_selection_start_offset is not None:
            self.enqueue_log("Preparing read aloud preview from selection.")
        else:
            self.enqueue_log("Preparing read aloud preview from the beginning.")
        self.preview_worker = threading.Thread(
            target=self.run_read_aloud,
            args=(request, resolved_start_offset, job_id, self.preview_stop_event),
            daemon=True,
        )
        self.preview_worker.start()
        self.update_playback_toggle_label()

    def run_read_aloud(
        self,
        request: SynthesisRequest,
        start_offset: int,
        job_id: int,
        stop_event: threading.Event,
    ) -> None:
        preview_paths: list[Path] = []
        try:
            preview_dir = PREVIEW_OUTPUT_PATH.resolve().parent
            for index, (chunk, segment) in enumerate(self.service.iter_segments(request, start_offset=start_offset), start=1):
                if stop_event.is_set() or job_id != self.preview_job_id:
                    break

                self.root.after(0, lambda offset=chunk.start: self.highlight_read_aloud_line(offset))
                preview_path = preview_dir / f"read-aloud-preview-{job_id}-{index}.wav"
                preview_paths.append(preview_path)
                export_audio_segment(segment, preview_path)
                self.root.after(0, self.update_playback_toggle_label)
                self.player.play_blocking(preview_path, stop_event)
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")
            error_message = str(exc)
            self.root.after(0, lambda message=error_message: messagebox.showerror("Read aloud failed", message))
        finally:
            if preview_paths:
                self.root.after(750, lambda paths=tuple(preview_paths): self.cleanup_preview_files(paths))
            if job_id == self.preview_job_id:
                self.root.after(0, self.clear_read_aloud_highlight)
            self.root.after(0, self.update_playback_toggle_label)

    def pause_playback(self) -> None:
        try:
            self.player.pause()
            self.update_playback_toggle_label()
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")

    def resume_playback(self) -> None:
        try:
            self.player.resume()
            self.update_playback_toggle_label()
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")

    def stop_playback(self) -> None:
        try:
            self.preview_stop_event.set()
            self.player.stop()
            self.clear_read_aloud_highlight()
            self.update_playback_toggle_label()
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")

    def toggle_playback_pause(self) -> None:
        if self.player.is_paused():
            self.resume_playback()
            return
        self.pause_playback()

    def update_playback_toggle_label(self) -> None:
        if self.player.is_paused():
            self.playback_toggle_label.set("⏵ Resume")
        else:
            self.playback_toggle_label.set("⏸ Pause")

    def get_text_content(self) -> str:
        return self.text.get("1.0", "end-1c")

    def text_index_to_offset(self, index: str) -> int:
        return int(self.text.count("1.0", index, "chars")[0])

    def offset_to_text_index(self, offset: int) -> str:
        return f"1.0 + {offset} chars"

    def get_read_aloud_start_offset(self, widget_index: str | None = None) -> int | None:
        content = self.get_text_content()
        if not content.strip():
            return None

        if widget_index is None:
            if self.text.tag_ranges("sel"):
                index = self.text.index("sel.first")
            elif self.last_selection_start_offset is not None:
                return find_word_start_offset(content, self.last_selection_start_offset)
            else:
                return find_word_start_offset(content, 0)
        else:
            index = widget_index
        offset = self.text_index_to_offset(index)
        return find_word_start_offset(content, offset)

    def update_selection_cache(self, _event=None) -> None:
        if self.preview_worker and self.preview_worker.is_alive():
            return
        if self.text.tag_ranges("sel"):
            self.last_selection_start_offset = self.text_index_to_offset("sel.first")
        else:
            self.last_selection_start_offset = None

    def cleanup_preview_files(self, paths: tuple[Path, ...] | list[Path] | None = None, retries: int = 5) -> None:
        candidates = list(paths) if paths is not None else list(PREVIEW_OUTPUT_PATH.resolve().parent.glob(PREVIEW_FILE_GLOB))
        if not candidates:
            return

        locked: list[Path] = []
        for path in candidates:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                locked.append(path)

        if locked and retries > 0:
            self.root.after(400, lambda pending=tuple(locked), remaining=retries - 1: self.cleanup_preview_files(pending, remaining))

    def clear_read_aloud_highlight(self) -> None:
        self.text.tag_remove(READ_ALOUD_LINE_TAG, "1.0", END)

    def highlight_read_aloud_line(self, offset: int) -> None:
        target_index = self.offset_to_text_index(offset)
        line_start = self.text.index(f"{target_index} linestart")
        line_end = self.text.index(f"{target_index} lineend +1c")
        self.clear_read_aloud_highlight()
        self.text.tag_add(READ_ALOUD_LINE_TAG, line_start, line_end)
        self.text.mark_set("insert", target_index)
        self.text.see(target_index)

    def on_text_click(self, event) -> None:
        index = self.text.index(f"@{event.x},{event.y}")
        start_offset = self.get_read_aloud_start_offset(index)
        if start_offset is None:
            return

        if self.preview_worker and self.preview_worker.is_alive():
            self.highlight_read_aloud_line(start_offset)
            self.root.after(0, lambda offset=start_offset: self.start_read_aloud_from(offset, reason="click_jump"))

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
            chunks = chunk_text_with_offsets(request.text)
            total_chunks = len(chunks)
            if total_chunks == 0:
                raise ValueError("Text is empty after cleanup.")

            combined = AudioSegment.silent(duration=0)
            for index, (_chunk, segment) in enumerate(self.service.iter_segments(request), start=1):
                combined += segment
                if index < total_chunks:
                    combined += AudioSegment.silent(duration=PAUSE_MS)
                self.root.after(
                    0,
                    lambda current=index, total=total_chunks: self.update_generation_progress(
                        current,
                        total,
                        f"Synthesizing chunk {current}/{total}...",
                    ),
                )

            self.root.after(0, lambda: self.generation_status.set("Saving audio file..."))
            self.enqueue_log(f"Exporting audio to {request.output_file}")
            export_audio_segment(combined, request.output_file)
            self.enqueue_log("Finished.")
            result = request.output_file
        except Exception as exc:
            self.enqueue_log(f"Error: {exc}")
            error_message = str(exc)
            self.root.after(0, lambda message=error_message: self.finish_generation_modal(None, error=message))
            return

        self.enqueue_log(f"Saved audio: {result}")
        self.root.after(0, lambda path=result: self.finish_generation_modal(path))


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
