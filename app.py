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
from urllib.parse import quote
from urllib.request import urlopen

import imageio_ffmpeg
import numpy as np

os.environ.setdefault("FFMPEG_BINARY", imageio_ffmpeg.get_ffmpeg_exe())
warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
    category=RuntimeWarning,
)
from tkinter import END
from tkinter import BooleanVar
from tkinter import DoubleVar
from tkinter import StringVar
from tkinter import Text
from tkinter import Tk
from tkinter import Toplevel
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from pydub import AudioSegment

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER = "Ana Florence"
ENGINE_AUTO = "Auto"
ENGINE_PIPER = "Piper"
ENGINE_XTTS = "XTTS v2"
ENGINE_POCKET = "Pocket TTS"
POCKET_DEFAULT_VOICE = "alba"
POCKET_VOICE_DIR = Path.cwd() / "voices" / "pocket"
POCKET_LANG_MAP: dict[str, str] = {
    "en": "english",
    "fr": "french",
    "de": "german",
    "pt": "portuguese",
    "it": "italian",
    "es": "spanish",
}
ENGINE_LANGUAGES: dict[str, list[str]] = {
    ENGINE_AUTO: ["en", "hu", "fr", "de", "pt", "it", "es"],
    ENGINE_PIPER: ["hu", "en"],
    ENGINE_XTTS: ["en", "hu", "fr", "de", "pt", "it", "es"],
    ENGINE_POCKET: ["en", "fr", "de", "pt", "it", "es"],
}
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
MP3_QUALITY_PRESETS = {
    "64 kbps": {"bitrate": "64k"},
    "128 kbps": {"bitrate": "128k"},
    "192 kbps (recommended)": {"bitrate": "192k"},
    "256 kbps": {"bitrate": "256k"},
    "320 kbps": {"bitrate": "320k"},
}
OGG_QUALITY_PRESETS = {
    "Low (q1)": {"quality_params": ["-q:a", "1"]},
    "Medium (q3)": {"quality_params": ["-q:a", "3"]},
    "High (q5)": {"quality_params": ["-q:a", "5"]},
    "Very High (q8)": {"quality_params": ["-q:a", "8"]},
    "Maximum (q10)": {"quality_params": ["-q:a", "10"]},
}
MAX_MERGE_CHUNKS = 500
PREVIEW_FILE_GLOB = "read-aloud-preview-*.wav"
MIN_CHAPTER_WORDS = 30
HEADING_PATTERNS: list[tuple[str, int]] = [
    (r'(?m)^\s*(?:Chapter|CHAPTER)\s+(\d+|[IVXLCDM]+)\b', 1),
    (r'(?m)^\s*(\d+)\.\s+(?:[A-Z][\w\s]{3,})$', 1),
    (r'(?m)^\s*(?:Part|PART)\s+(\d+|[IVXLCDM]+)\b', 1),
    (r'(?m)^\s*(?:Section|SECTION)\s+(\d+)\b', 2),
    (r'(?m)^\s*[IVXLCDM]+\.\s', 1),
]
FONT_BODY = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
FONT_MONO = "Consolas" if sys.platform == "win32" else "Liberation Mono"

def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip().rstrip('.')


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


def export_audio_segment(
    audio: AudioSegment,
    output_file: Path,
    bitrate: str | None = None,
    quality_params: list[str] | None = None,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_format = output_format_for_path(output_file)
    export_kwargs: dict[str, object] = {"format": output_format}

    if quality_params is not None:
        export_kwargs["parameters"] = ["-ar", "44100"] + quality_params
    elif bitrate is not None:
        export_kwargs["bitrate"] = bitrate
        export_kwargs["parameters"] = ["-ar", "44100"]
    elif output_format in {"mp3", "ogg"}:
        export_kwargs["bitrate"] = "192k"
        export_kwargs["parameters"] = ["-ar", "44100"]
    else:
        export_kwargs["parameters"] = ["-ar", "44100"]

    audio.export(output_file, **export_kwargs)


class DocumentExtractor:
    SUPPORTED = {
        ".docx": "DOCX",
        ".odt": "ODT",
        ".pdf": "PDF",
        ".epub": "EPUB",
        ".mobi": "MOBI",
    }

    @staticmethod
    def extract_text(filepath: Path, from_page: int | None = None, to_page: int | None = None) -> str:
        suffix = filepath.suffix.lower()
        if suffix == ".docx":
            return DocumentExtractor._extract_docx(filepath)
        if suffix == ".odt":
            return DocumentExtractor._extract_odt(filepath)
        if suffix == ".pdf":
            return DocumentExtractor._extract_pdf(filepath, from_page=from_page, to_page=to_page)
        if suffix == ".epub":
            return DocumentExtractor._extract_epub(filepath)
        if suffix == ".mobi":
            return DocumentExtractor._extract_mobi(filepath)
        raise ValueError(f"Unsupported document format: {suffix}")

    @staticmethod
    def _extract_docx(filepath: Path) -> str:
        try:
            import docx
        except ImportError:
            raise RuntimeError("python-docx not installed. Run: pip install python-docx")
        doc = docx.Document(str(filepath))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    @staticmethod
    def _extract_odt(filepath: Path) -> str:
        try:
            from odf import teletype
            from odf import text as odf_text
            from odf.opendocument import load
        except ImportError:
            raise RuntimeError("odfpy not installed. Run: pip install odfpy")
        doc = load(str(filepath))
        paragraphs = []
        for elem in doc.getElementsByType(odf_text.P):
            content = teletype.extractText(elem).strip()
            if content:
                paragraphs.append(content)
        return "\n\n".join(paragraphs)

    @staticmethod
    def _extract_pdf(filepath: Path, from_page: int | None = None, to_page: int | None = None) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("pypdf not installed. Run: pip install pypdf")
        reader = PdfReader(str(filepath))
        total_pages = len(reader.pages)
        start = (from_page or 1) - 1
        end = to_page if to_page else total_pages
        start = max(0, min(start, total_pages - 1))
        end = max(start + 1, min(end, total_pages))
        pages = []
        for page in reader.pages[start:end]:
            text = page.extract_text()
            if text:
                text = re.sub(r"\n{3,}", "\n\n", text)
                text = re.sub(r" {2,}", " ", text)
                pages.append(text.strip())
        return "\n\n".join(pages)

    @staticmethod
    def _extract_epub(filepath: Path) -> str:
        try:
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub
        except ImportError:
            raise RuntimeError("ebooklib and/or beautifulsoup4 not installed. Run: pip install ebooklib beautifulsoup4")
        book = epub.read_epub(str(filepath))
        chapters = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text)
            if text.strip():
                chapters.append(text.strip())
        return "\n\n".join(chapters)

    @staticmethod
    def _extract_mobi(filepath: Path) -> str:
        try:
            from mobi import extract
        except ImportError:
            raise RuntimeError("mobi not installed. Run: pip install mobi")
        import shutil as _shutil_mod

        temp_dir = None
        try:
            temp_dir, extracted_path = extract(str(filepath))
            temp_dir = Path(temp_dir)
            extracted = Path(extracted_path)

            if extracted.suffix.lower() == ".epub":
                text = DocumentExtractor._extract_epub(extracted)
            elif extracted.suffix.lower() == ".html":
                try:
                    from bs4 import BeautifulSoup
                except ImportError:
                    raise RuntimeError(
                        "beautifulsoup4 not installed for MOBI HTML extraction. "
                        "Run: pip install beautifulsoup4"
                    )
                soup = BeautifulSoup(extracted.read_text(encoding="utf-8", errors="replace"), "html.parser")
                text = soup.get_text(separator="\n")
                text = re.sub(r"\n{3,}", "\n\n", text)
            else:
                text = extracted.read_text(encoding="utf-8", errors="replace")

            if not text.strip():
                raise RuntimeError("No text extracted from MOBI file.")
            return text
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"MOBI extraction failed: {exc}") from exc
        finally:
            if temp_dir is not None:
                try:
                    _shutil_mod.rmtree(str(temp_dir), ignore_errors=True)
                except Exception:
                    pass

    @staticmethod
    def extract_chapters(
        filepath: Path,
        min_level: str = "all",
        from_page: int | None = None,
        to_page: int | None = None,
    ) -> list[tuple[str, str]]:
        suffix = filepath.suffix.lower()
        if suffix == ".docx":
            return DocumentExtractor._extract_docx_chapters(filepath, min_level)
        if suffix == ".odt":
            return DocumentExtractor._extract_odt_chapters(filepath, min_level)
        if suffix == ".pdf":
            return DocumentExtractor._extract_pdf_chapters(filepath, min_level, from_page=from_page, to_page=to_page)
        if suffix == ".epub":
            return DocumentExtractor._extract_epub_chapters(filepath, min_level)
        if suffix == ".mobi":
            return DocumentExtractor._extract_mobi_chapters(filepath, min_level)
        return [(("", DocumentExtractor.extract_text(filepath, from_page=from_page, to_page=to_page)))]

    @staticmethod
    def _heading_level_for_setting(min_level: str) -> int | None:
        if min_level == "h1":
            return 1
        if min_level == "h1-h2":
            return 2
        if min_level == "h1-h3":
            return 3
        return None

    @staticmethod
    def _heading_level_from_style(style_name: str) -> int | None:
        if not style_name:
            return None
        match = re.match(r'[Hh]eading\s*(\d+)', style_name)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_docx_chapters(filepath: Path, min_level: str = "all") -> list[tuple[str, str]]:
        try:
            import docx
        except ImportError:
            raise RuntimeError("python-docx not installed. Run: pip install python-docx")
        doc = docx.Document(str(filepath))
        max_level = DocumentExtractor._heading_level_for_setting(min_level)

        chapters: list[tuple[str, str]] = []
        current_title = ""
        current_content: list[str] = []

        for p in doc.paragraphs:
            heading_level = DocumentExtractor._heading_level_from_style(p.style.name if p.style else "")
            text = p.text.strip()
            if not text:
                continue

            if heading_level is not None and (max_level is None or heading_level <= max_level):
                if current_content:
                    chapters.append((current_title, "\n\n".join(current_content)))
                current_title = text
                current_content = []
            else:
                current_content.append(text)

        if current_content:
            chapters.append((current_title, "\n\n".join(current_content)))

        if not chapters:
            return [("", DocumentExtractor._extract_docx(filepath))]

        return chapters

    @staticmethod
    def _extract_odt_chapters(filepath: Path, min_level: str = "all") -> list[tuple[str, str]]:
        try:
            from odf import teletype
            from odf.opendocument import load
        except ImportError:
            raise RuntimeError("odfpy not installed. Run: pip install odfpy")
        doc = load(str(filepath))
        max_level = DocumentExtractor._heading_level_for_setting(min_level)

        chapters: list[tuple[str, str]] = []
        current_title = ""
        current_content: list[str] = []

        body = getattr(doc, "body", None)
        if body is None:
            return [("", DocumentExtractor._extract_odt(filepath))]

        children = getattr(body, "childNodes", [])
        if not children:
            return [("", DocumentExtractor._extract_odt(filepath))]

        text_children: list = []
        for body_child in children:
            tag = getattr(body_child, "tagName", "")
            if tag in ("text:h", "text:p"):
                text_children = children
                break
            nested = getattr(body_child, "childNodes", [])
            if nested:
                text_children = nested
                break

        if not text_children:
            text_children = children

        has_headings = False

        for child in text_children:
            tag_name = getattr(child, "tagName", "")
            text_content = teletype.extractText(child).strip()

            if tag_name == "text:h":
                has_headings = True
                outline_level = int(child.getAttribute("outlinelevel") or "1")
                if max_level is None or outline_level <= max_level:
                    if current_content:
                        chapters.append((current_title, "\n\n".join(current_content)))
                    current_title = text_content
                    current_content = []
                    continue
                current_content.append(text_content)
            elif tag_name == "text:p":
                if text_content:
                    current_content.append(text_content)

        if current_content:
            chapters.append((current_title, "\n\n".join(current_content)))

        if not has_headings:
            return [("", DocumentExtractor._extract_odt(filepath))]

        return chapters

    @staticmethod
    def _extract_pdf_chapters(
        filepath: Path,
        min_level: str = "all",
        from_page: int | None = None,
        to_page: int | None = None,
    ) -> list[tuple[str, str]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("pypdf not installed. Run: pip install pypdf")
        reader = PdfReader(str(filepath))

        if reader.outline:
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(
                reader, from_page=from_page, to_page=to_page
            )
            if len(chapters) >= 2:
                return chapters

        return DocumentExtractor._extract_pdf_chapters_by_pattern(filepath, from_page=from_page, to_page=to_page)

    @staticmethod
    def _extract_pdf_chapters_from_outline(
        reader,
        from_page: int | None = None,
        to_page: int | None = None,
    ) -> list[tuple[str, str]]:
        total_pages = len(reader.pages)
        user_start = max(0, (from_page or 1) - 1)
        user_end = min(total_pages, to_page) if to_page else total_pages
        user_start = max(0, min(user_start, total_pages - 1))
        user_end = max(user_start + 1, min(user_end, total_pages))

        pages_text: dict[int, str] = {}
        for page_num in range(user_start, user_end):
            page = reader.pages[page_num]
            text = page.extract_text()
            if text:
                text = re.sub(r"\n{3,}", "\n\n", text)
                text = re.sub(r" {2,}", " ", text)
                pages_text[page_num] = text.strip()

        outline_items: list[tuple[str, int]] = []

        def walk_outline(items, depth=0):
            for item in items:
                if isinstance(item, list):
                    walk_outline(item, depth + 1)
                else:
                    title = getattr(item, "title", "")
                    if not title:
                        continue
                    title = title.strip()
                    try:
                        page_num = reader.get_destination_page_number(item)
                    except Exception:
                        continue
                    outline_items.append((title, page_num))

        walk_outline(reader.outline)

        if not outline_items:
            return []

        chapters: list[tuple[str, str]] = []
        for i, (title, start_page) in enumerate(outline_items):
            end_page = outline_items[i + 1][1] if i + 1 < len(outline_items) else len(reader.pages)
            chapter_pages = []
            for pg in range(start_page, min(end_page, len(reader.pages))):
                if pg in pages_text:
                    chapter_pages.append(pages_text[pg])
            content = "\n\n".join(chapter_pages).strip()
            if content:
                chapters.append((title, content))

        return chapters

    @staticmethod
    def _extract_pdf_chapters_by_pattern(
        filepath: Path,
        from_page: int | None = None,
        to_page: int | None = None,
    ) -> list[tuple[str, str]]:
        full_text = DocumentExtractor._extract_pdf(filepath, from_page=from_page, to_page=to_page)
        if not full_text.strip():
            return [("", "")]

        split_points: list[tuple[int, str]] = []
        for pattern, _level in HEADING_PATTERNS:
            for match in re.finditer(pattern, full_text):
                pos = match.start()
                if all(abs(pos - existing) > 5 for existing, _ in split_points):
                    split_points.append((pos, match.group().strip()))
            if split_points:
                break

        if not split_points:
            return [("", full_text)]

        split_points.sort(key=lambda x: x[0])

        chapters: list[tuple[str, str]] = []
        for i, (pos, title) in enumerate(split_points):
            end = split_points[i + 1][0] if i + 1 < len(split_points) else len(full_text)
            content = full_text[pos:end].strip()
            if content:
                chapters.append((title, content))

        if not chapters:
            return [("", full_text)]

        return chapters

    @staticmethod
    def _extract_epub_chapters(filepath: Path, min_level: str = "all") -> list[tuple[str, str]]:
        try:
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub
        except ImportError:
            raise RuntimeError("ebooklib and/or beautifulsoup4 not installed. Run: pip install ebooklib beautifulsoup4")
        book = epub.read_epub(str(filepath))
        max_level = DocumentExtractor._heading_level_for_setting(min_level)

        chapters: list[tuple[str, str]] = []
        current_title = ""
        current_content: list[str] = []
        has_headings = False

        def _detect_level(tag_name: str) -> int | None:
            if tag_name and tag_name.startswith("h") and len(tag_name) == 2:
                try:
                    return int(tag_name[1])
                except ValueError:
                    return None
            return None

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")

            for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"], recursive=False):
                tag_name = getattr(element, "name", "")
                text_content = element.get_text(separator="\n").strip()
                if not text_content:
                    continue

                heading_level = _detect_level(tag_name)
                if heading_level is not None and (max_level is None or heading_level <= max_level):
                    has_headings = True
                    if current_content:
                        chapters.append((current_title, "\n\n".join(current_content)))
                    current_title = text_content
                    current_content = []
                else:
                    current_content.append(text_content)

            text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text)
            if text.strip():
                for elem in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"], recursive=True):
                    if _detect_level(getattr(elem, "name", "")):
                        has_headings = True
                        break

        if current_content:
            chapters.append((current_title, "\n\n".join(current_content)))

        if not has_headings or not chapters:
            return [("", DocumentExtractor._extract_epub(filepath))]

        return chapters

    @staticmethod
    def _extract_mobi_chapters(filepath: Path, min_level: str = "all") -> list[tuple[str, str]]:
        try:
            from mobi import extract
        except ImportError:
            raise RuntimeError("mobi not installed. Run: pip install mobi")
        import shutil as _shutil_mod

        temp_dir = None
        try:
            temp_dir, extracted_path = extract(str(filepath))
            temp_dir = Path(temp_dir)
            extracted = Path(extracted_path)

            if extracted.suffix.lower() == ".epub":
                result = DocumentExtractor._extract_epub_chapters(extracted, min_level)
            else:
                result = [("", DocumentExtractor._extract_mobi(filepath))]

            return result
        except Exception as exc:
            raise RuntimeError(f"MOBI extraction failed: {exc}") from exc
        finally:
            if temp_dir is not None:
                try:
                    _shutil_mod.rmtree(str(temp_dir), ignore_errors=True)
                except Exception:
                    pass


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
    speed: float = 1.0


@dataclass(frozen=True)
class ChapterEntry:
    source_path: Path
    index: int
    title: str
    content: str
    word_count: int


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


def get_default_music_folder() -> Path:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        csidl = 13  # CSIDL_MYMUSIC
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
            return Path(buf.value)
        return Path.home() / "Music"

    if sys.platform == "darwin":
        return Path.home() / "Music"

    user_dirs = Path.home() / ".config" / "user-dirs.dirs"
    if user_dirs.exists():
        for line in user_dirs.read_text().splitlines():
            if line.startswith("XDG_MUSIC_DIR="):
                dir_path = line.split("=", 1)[1].strip('"').strip("'")
                dir_path = dir_path.replace("$HOME", str(Path.home()))
                resolved = Path(dir_path).expanduser()
                if resolved.exists():
                    return resolved
    return Path.home() / "Music"


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
        if request.speed != 1.0:
            kwargs["speed"] = request.speed
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
            from piper.config import SynthesisConfig

            syn_config = None
            if request.speed != 1.0:
                syn_config = SynthesisConfig(length_scale=1.0 / request.speed)
            for audio_chunk in voice.synthesize(chunk.text, syn_config=syn_config):
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


class PocketTTSService:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._log = log
        self._model = None
        self._loaded_language = None
        self._voice_states: dict = {}
        self._sample_rate = 24000

    def _resolve_language(self, lang_code: str) -> str:
        return POCKET_LANG_MAP.get(lang_code, "english")

    @staticmethod
    def _voice_cache_path(voice_source: str) -> Path | None:
        source_path = Path(voice_source)
        if source_path.is_file():
            return None
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", voice_source)
        return POCKET_VOICE_DIR / f"{safe}.safetensors"

    def ensure_loaded(self, lang_code: str = "en") -> None:
        lang = self._resolve_language(lang_code)
        if self._model is not None and self._loaded_language == lang:
            return
        if self._model is not None:
            self._log(
                f"Language changed ({self._loaded_language} → {lang}), reloading model..."
            )
            self._voice_states.clear()
        self._log(f"Loading Pocket TTS model (language: {lang})...")
        try:
            from pocket_tts import TTSModel
        except Exception as exc:
            raise RuntimeError(
                "pocket-tts is not installed in this environment. "
                "Run the setup script first (`.\\setup.ps1` on Windows or `./setup.sh` on Linux/macOS)."
            ) from exc
        self._model = TTSModel.load_model(language=lang)
        self._sample_rate = self._model.sample_rate
        self._loaded_language = lang
        self._log("Pocket TTS model is ready.")

    def _get_voice_state(self, voice_source: str) -> dict:
        if voice_source in self._voice_states:
            return self._voice_states[voice_source]
        cache_path = self._voice_cache_path(voice_source)
        voice_arg = str(cache_path) if cache_path is not None and cache_path.exists() else voice_source
        self._log(f"Loading voice from: {voice_arg}")
        state = self._model.get_state_for_audio_prompt(voice_arg)
        if cache_path is not None and not cache_path.exists():
            POCKET_VOICE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                from pocket_tts import export_model_state
                export_model_state(state, cache_path)
            except Exception:
                pass
        self._voice_states[voice_source] = state
        return state

    def iter_segments(self, request: SynthesisRequest, start_offset: int = 0):
        self.ensure_loaded(request.language)
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        chunks = chunk_text_with_offsets(request.text, start_offset=start_offset)
        if not chunks:
            raise ValueError("Text is empty after cleanup.")
        if request.speaker_wav:
            voice_source = request.speaker_wav
        else:
            voice_source = request.speaker_name or POCKET_DEFAULT_VOICE
        voice_state = self._get_voice_state(voice_source)
        self._log(f"Prepared {len(chunks)} chunk(s) for synthesis.")
        for index, chunk in enumerate(chunks, start=1):
            self._log(f"Synthesizing chunk {index}/{len(chunks)}")
            audio_tensor = self._model.generate_audio(
                voice_state, chunk.text, copy_state=True
            )
            array = audio_tensor.cpu().numpy()
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


class SynthesisCoordinator:
    def __init__(self, log: Callable[[str], None]) -> None:
        self._xtts = XTTSService(log)
        self._piper = PiperService(log)
        self._pocket = PocketTTSService(log)

    @staticmethod
    def resolve_engine(request: SynthesisRequest) -> str:
        if request.engine == ENGINE_AUTO:
            return ENGINE_XTTS if request.speaker_wav else ENGINE_PIPER
        return request.engine

    def synthesize(self, request: SynthesisRequest) -> Path:
        resolved_engine = self.resolve_engine(request)
        if resolved_engine == ENGINE_PIPER:
            return self._piper.synthesize(request)
        if resolved_engine == ENGINE_POCKET:
            return self._pocket.synthesize(request)
        return self._xtts.synthesize(request)

    def iter_segments(self, request: SynthesisRequest, start_offset: int = 0):
        resolved_engine = self.resolve_engine(request)
        if resolved_engine == ENGINE_PIPER:
            yield from self._piper.iter_segments(request, start_offset=start_offset)
            return
        if resolved_engine == ENGINE_POCKET:
            yield from self._pocket.iter_segments(request, start_offset=start_offset)
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
        self.app = app
        self.window = Toplevel(app.root)
        self.window.transient(app.root)
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

    def _build_ui(self) -> None:  # pragma: no cover
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
        ttk.Button(actions, text="↓ Download Selected", style="Accent.TButton", command=self.download_selected).pack(side="right")
        ttk.Button(actions, text="★ Set As Default", command=self.set_selected_default).pack(side="right", padx=(0, 8))

        ttk.Label(frame, textvariable=self.status).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def refresh_catalog(self) -> None:
        if self.downloading:
            return
        self.status.set("Refreshing Piper voice catalog...")
        threading.Thread(target=self.load_catalog, daemon=True).start()

    def load_catalog(self) -> None:
        try:
            with urlopen(PIPER_VOICES_JSON_URL, timeout=15) as response:
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
            import shutil

            PIPER_VOICE_DIR.mkdir(parents=True, exist_ok=True)
            info = self.catalog.get(voice_code, {})
            files = info.get("files", {})

            for rel_path in files:
                if not rel_path.endswith((".onnx", ".onnx.json")):
                    continue

                local_path = PIPER_VOICE_DIR / Path(rel_path).name
                if local_path.exists() and local_path.stat().st_size > 0:
                    continue

                url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{quote(rel_path)}?download=true"
                with urlopen(url, timeout=60) as resp:
                    with open(local_path, "wb") as f:
                        shutil.copyfileobj(resp, f)
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


class DocumentToAudioWizard:
    MP3_PRESETS = MP3_QUALITY_PRESETS
    OGG_PRESETS = OGG_QUALITY_PRESETS
    MAX_MERGE_CHUNKS = MAX_MERGE_CHUNKS

    def __init__(self, app: "App") -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.transient(app.root)
        self.window.title("Document to Audio Converter")
        self.window.geometry("1000x760")
        self.window.minsize(920, 680)

        self.documents: list[Path] = []
        self.doc_status: dict[Path, str] = {}
        self.extracted_texts: dict[ChapterEntry, str] = {}
        self.chunk_counts: dict[ChapterEntry, int] = {}
        self._chapter_entries: dict[Path, list[ChapterEntry]] = {}
        self._total_chunks: int = 0

        self.worker: threading.Thread | None = None
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.stop_event = threading.Event()

        self.output_format = StringVar(value="MP3")
        default_quality = list(self.MP3_PRESETS.keys())[0]
        self.quality_preset = StringVar(value=default_quality)
        self.merge_files = BooleanVar(value=False)
        self.output_folder = StringVar(value=str(get_default_music_folder().resolve()))
        self.split_chapters = BooleanVar(value=False)
        self.chapter_level = StringVar(value="all")

        self.wizard_speed = DoubleVar(value=self.app.speed.get())

        self.from_page = StringVar(value="")
        self.to_page = StringVar(value="")

        self.wizard_engine = StringVar(value=app.engine.get())
        self.wizard_piper_voice_label = StringVar(value=app.piper_voice_label.get())
        self.wizard_speaker_name = StringVar(value=app.speaker_name.get())
        self.wizard_speaker_wav = StringVar(value=app.speaker_wav.get())

        self.phase_text = StringVar(value="")
        self.overall_text = StringVar(value="Idle")
        self.file_text = StringVar(value="")
        self.pause_button_text = StringVar(value="Pause")

        self._build_ui()
        self._on_split_chapters_toggled()
        self.output_format.trace_add("write", self._on_format_changed)
        self.wizard_engine.trace_add("write", self._on_wizard_engine_changed)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:  # pragma: no cover
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill="both", expand=True)

        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 8))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Document to Audio Converter", font=(FONT_BODY, 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        header_actions = ttk.Frame(header)
        header_actions.grid(row=0, column=1, sticky="e")
        self.start_button = ttk.Button(
            header_actions, text="Start", style="Accent.TButton", command=self._start_processing
        )
        self.start_button.pack(side="left")
        self.pause_button = ttk.Button(
            header_actions, textvariable=self.pause_button_text, command=self._toggle_pause
        )
        self.pause_button.pack(side="left", padx=(8, 0))
        ttk.Button(header_actions, text="Stop", command=self._stop_processing).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(header_actions, text="Close", command=self._on_close).pack(
            side="left", padx=(8, 0)
        )

        docs_frame = ttk.LabelFrame(frame, text="Documents", padding=10)
        docs_frame.pack(fill="both", expand=True)
        docs_frame.columnconfigure(0, weight=1)

        columns = ("filename", "format", "size", "status")
        self.tree = ttk.Treeview(docs_frame, columns=columns, show="headings", height=8)
        self.tree.heading("filename", text="Filename")
        self.tree.heading("format", text="Format")
        self.tree.heading("size", text="Size")
        self.tree.heading("status", text="Status")
        self.tree.column("filename", width=360)
        self.tree.column("format", width=70, anchor="center")
        self.tree.column("size", width=80, anchor="center")
        self.tree.column("status", width=280)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(docs_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        doc_actions = ttk.Frame(docs_frame)
        doc_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(doc_actions, text="Add Documents", command=self._add_documents).pack(side="left")
        ttk.Button(doc_actions, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(doc_actions, text="Clear All", command=self._clear_all).pack(side="right")

        settings_frame = ttk.LabelFrame(frame, text="Output Settings", padding=10)
        settings_frame.pack(fill="x", pady=(10, 0))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)
        settings_frame.columnconfigure(5, weight=1)

        ttk.Label(settings_frame, text="Format").grid(row=0, column=0, sticky="w", pady=4)
        self.format_box = ttk.Combobox(
            settings_frame,
            textvariable=self.output_format,
            values=list(SUPPORTED_OUTPUT_FORMATS.values()),
            state="readonly",
            width=10,
        )
        self.format_box.grid(row=0, column=1, sticky="w", pady=4, padx=(0, 18))
        self.format_box.set("MP3")

        ttk.Label(settings_frame, text="Quality").grid(row=0, column=2, sticky="w", pady=4)
        self.quality_box = ttk.Combobox(
            settings_frame,
            textvariable=self.quality_preset,
            values=list(self.MP3_PRESETS.keys()),
            state="readonly",
            width=22,
        )
        self.quality_box.grid(row=0, column=3, sticky="w", pady=4, padx=(0, 18))

        ttk.Label(settings_frame, text="Engine").grid(row=0, column=4, sticky="w", pady=4)
        self.wizard_engine_box = ttk.Combobox(
            settings_frame,
            textvariable=self.wizard_engine,
            values=[ENGINE_AUTO, ENGINE_PIPER, ENGINE_XTTS, ENGINE_POCKET],
            state="readonly",
            width=14,
        )
        self.wizard_engine_box.grid(row=0, column=5, sticky="w", pady=4)

        ttk.Label(settings_frame, text="Piper Voice").grid(row=1, column=0, sticky="w", pady=4)
        self.wizard_piper_voice_box = ttk.Combobox(
            settings_frame,
            textvariable=self.wizard_piper_voice_label,
            values=list(self.app.piper_voice_options.keys()),
            state="readonly",
            width=28,
        )
        self.wizard_piper_voice_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(settings_frame, text="Speaker").grid(row=1, column=4, sticky="w", pady=4, padx=(18, 0))
        self.wizard_speaker_name_entry = ttk.Entry(
            settings_frame, textvariable=self.wizard_speaker_name
        )
        self.wizard_speaker_name_entry.grid(row=1, column=5, sticky="ew", pady=4)

        ttk.Label(settings_frame, text="Reference WAV").grid(row=2, column=0, sticky="w", pady=4)
        self.wizard_speaker_wav_entry = ttk.Entry(
            settings_frame, textvariable=self.wizard_speaker_wav
        )
        self.wizard_speaker_wav_entry.grid(row=2, column=1, columnspan=4, sticky="ew", pady=4)
        self.wizard_speaker_wav_button = ttk.Button(
            settings_frame, text="Browse", command=self._pick_wizard_reference_wav
        )
        self.wizard_speaker_wav_button.grid(row=2, column=5, sticky="e", pady=4)

        self.wizard_speed_label = ttk.Label(settings_frame, text="Speed: 1.0x")
        self.wizard_speed_label.grid(row=3, column=0, sticky="w", pady=4)
        self.wizard_speed_slider = ttk.Scale(
            settings_frame,
            from_=0.5,
            to=2.0,
            variable=self.wizard_speed,
            orient="horizontal",
            command=self._on_wizard_speed_changed,
        )
        self.wizard_speed_slider.grid(row=3, column=1, columnspan=5, sticky="ew", pady=4)

        ttk.Checkbutton(
            settings_frame,
            text="Merge all documents into one audio file",
            variable=self.merge_files,
        ).grid(row=4, column=0, columnspan=6, sticky="w", pady=(6, 4))

        split_row = ttk.Frame(settings_frame)
        split_row.grid(row=5, column=0, columnspan=6, sticky="ew", pady=(6, 4))
        self.split_chapters_check = ttk.Checkbutton(
            split_row,
            text="Split by chapter (experimental)",
            variable=self.split_chapters,
            command=self._on_split_chapters_toggled,
        )
        self.split_chapters_check.pack(side="left")
        ttk.Label(split_row, text="Level:").pack(side="left", padx=(12, 4))
        self.chapter_level_box = ttk.Combobox(
            split_row,
            textvariable=self.chapter_level,
            values=["all", "h1", "h1-h2", "h1-h3"],
            state="readonly",
            width=8,
        )
        self.chapter_level_box.pack(side="left")

        ttk.Label(settings_frame, text="Output Folder").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(settings_frame, textvariable=self.output_folder).grid(
            row=6, column=1, columnspan=4, sticky="ew", pady=4
        )
        ttk.Button(settings_frame, text="Browse...", command=self._pick_output_folder).grid(
            row=6, column=5, sticky="e", pady=4, padx=(8, 0)
        )

        ttk.Label(settings_frame, text="Pages (PDF)").grid(row=7, column=0, sticky="w", pady=4)
        page_row = ttk.Frame(settings_frame)
        page_row.grid(row=7, column=1, columnspan=5, sticky="w", pady=4)
        ttk.Label(page_row, text="From:").pack(side="left")
        self.from_page_entry = ttk.Entry(page_row, textvariable=self.from_page, width=6)
        self.from_page_entry.pack(side="left", padx=(4, 12))
        ttk.Label(page_row, text="To:").pack(side="left")
        self.to_page_entry = ttk.Entry(page_row, textvariable=self.to_page, width=6)
        self.to_page_entry.pack(side="left", padx=(4, 0))

        progress_frame = ttk.LabelFrame(frame, text="Progress", padding=10)
        progress_frame.pack(fill="x", pady=(10, 0))
        progress_frame.columnconfigure(0, weight=1)

        ttk.Label(progress_frame, textvariable=self.phase_text, style="Hint.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(progress_frame, text="Overall:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(progress_frame, textvariable=self.overall_text, style="Hint.TLabel").grid(
            row=1, column=1, sticky="e", pady=(6, 0)
        )
        self.overall_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=100)
        self.overall_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 6))

        ttk.Label(progress_frame, text="File:").grid(row=3, column=0, sticky="w")
        ttk.Label(progress_frame, textvariable=self.file_text, style="Hint.TLabel").grid(
            row=3, column=1, sticky="e"
        )
        self.file_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=100)
        self.file_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    def _on_wizard_speed_changed(self, *args) -> None:
        speed_val = round(self.wizard_speed.get(), 1)
        self.wizard_speed_label.configure(text=f"Speed: {speed_val:.1f}x")

    def _parse_page_range(self) -> tuple[int | None, int | None]:
        from_str = self.from_page.get().strip()
        to_str = self.to_page.get().strip()
        from_page = int(from_str) if from_str else None
        to_page = int(to_str) if to_str else None
        return from_page, to_page

    def _on_wizard_engine_changed(self, *_args) -> None:
        engine = self.wizard_engine.get()
        piper_enabled = engine in (ENGINE_AUTO, ENGINE_PIPER)
        if engine == ENGINE_AUTO:
            resolved = ENGINE_XTTS if self.wizard_speaker_wav.get().strip() else ENGINE_PIPER
        else:
            resolved = engine
        speaker_state = "normal" if resolved in (ENGINE_XTTS, ENGINE_POCKET) else "disabled"
        self.wizard_piper_voice_box.configure(state="readonly" if piper_enabled else "disabled")
        self.wizard_speaker_name_entry.configure(state=speaker_state)
        self.wizard_speaker_wav_entry.configure(state=speaker_state)
        self.wizard_speaker_wav_button.configure(state=speaker_state)

    def _on_format_changed(self, *_args) -> None:
        fmt = self.output_format.get()
        if fmt == "OGG":
            presets = list(self.OGG_PRESETS.keys())
            self.quality_preset.set(presets[0])
            self.quality_box.configure(values=presets, state="readonly")
        elif fmt == "WAV":
            self.quality_box.configure(values=["Lossless (no quality setting)"], state="disabled")
            self.quality_preset.set("Lossless (no quality setting)")
        else:
            presets = list(self.MP3_PRESETS.keys())
            self.quality_preset.set(presets[0])
            self.quality_box.configure(values=presets, state="readonly")

    def _on_split_chapters_toggled(self) -> None:
        enabled = self.split_chapters.get()
        if hasattr(self, "chapter_level_box"):
            self.chapter_level_box.configure(state="readonly" if enabled else "disabled")
        if not hasattr(self, "start_button") or not hasattr(self, "tree"):
            return
        if self.extracted_texts:
            self.extracted_texts.clear()
            self.chunk_counts.clear()
            self._chapter_entries.clear()
            self._total_chunks = 0
            for doc_path in self.documents:
                self._update_doc_status(doc_path, "Ready — needs re-extraction")
            self.start_button.configure(state="disabled")
            self.app.enqueue_log("Chapter split setting changed — re-extraction required.")

    def _add_documents(self) -> None:
        formats = " ".join(f"*{ext}" for ext in DocumentExtractor.SUPPORTED)
        paths = filedialog.askopenfilenames(
            parent=self.window,
            title="Select documents",
            filetypes=[
                ("All supported documents", formats),
                ("DOCX files", "*.docx"),
                ("ODT files", "*.odt"),
                ("PDF files", "*.pdf"),
                ("EPUB files", "*.epub"),
                ("MOBI files", "*.mobi"),
                ("All files", "*.*"),
            ],
        )
        for path_str in paths:
            path = Path(path_str)
            if path not in self.documents:
                self.documents.append(path)
                self.doc_status[path] = "Ready"
        self._refresh_tree()

    def _remove_selected(self) -> None:
        selection = self.tree.selection()
        for iid in selection:
            path = Path(iid)
            if path in self.documents:
                self.documents.remove(path)
                self.doc_status.pop(path, None)
        self._refresh_tree()

    def _clear_all(self) -> None:
        self.documents.clear()
        self.doc_status.clear()
        self._refresh_tree()

    def _pick_output_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self.window,
            title="Choose output folder",
            initialdir=self.output_folder.get(),
        )
        if folder:
            self.output_folder.set(folder)

    def _pick_wizard_reference_wav(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Choose reference voice WAV",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac"), ("All files", "*.*")],
        )
        if path:
            self.wizard_speaker_wav.set(path)

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for path in self.documents:
            size_kb = path.stat().st_size / 1024 if path.exists() else 0
            self.tree.insert(
                "",
                "end",
                iid=str(path),
                values=(
                    path.name,
                    DocumentExtractor.SUPPORTED.get(path.suffix.lower(), "Unknown"),
                    f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB",
                    self.doc_status.get(path, "Ready"),
                ),
            )
        self.start_button.configure(state="normal" if self.documents else "disabled")

    def _set_buttons_state(self, processing: bool) -> None:
        state = "disabled" if processing else "normal"
        self.start_button.configure(state=state)
        self.pause_button_text.set("Pause")

    def _start_processing(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.documents:
            messagebox.showinfo("No documents", "Add at least one document first.")
            return

        output_folder = Path(self.output_folder.get())
        output_folder.mkdir(parents=True, exist_ok=True)

        self.doc_status = {p: "Queued" for p in self.documents}
        self.extracted_texts.clear()
        self.chunk_counts.clear()
        self._chapter_entries.clear()
        self._refresh_tree()

        self._set_buttons_state(processing=True)
        self.stop_event.clear()
        self.pause_event.set()

        self.worker = threading.Thread(target=self._run_processing, args=(output_folder,), daemon=True)
        self.worker.start()

    def _run_processing(self, output_folder: Path) -> None:
        try:
            self._do_extraction()
            if self.stop_event.is_set():
                return self._finish("Stopped.")

            self._do_preparation()
            if self.stop_event.is_set():
                return self._finish("Stopped.")

            if self.merge_files.get():
                self._do_synthesis_merged(output_folder)
            else:
                self._do_synthesis_per_file(output_folder)
        except Exception as exc:
            self.app.enqueue_log(f"Document wizard error: {exc}")
            self.window.after(0, lambda e=str(exc): self._finish(f"Error: {e}"))

    def _do_extraction(self) -> None:
        docs = list(self.documents)
        total = len(docs)
        chapter_formats = {".docx", ".odt", ".pdf", ".epub"}
        from_page, to_page = self._parse_page_range()
        for i, doc_path in enumerate(docs):
            if self.stop_event.is_set():
                return
            self.window.after(0, lambda p=doc_path, s="Extracting...": self._update_doc_status(p, s))
            self.window.after(
                0,
                lambda cur=i + 1, tot=total: self.phase_text.set(
                    f"Extracting text ({cur}/{tot})..."
                ),
            )
            self.window.after(
                0,
                lambda cur=i + 1, tot=total: self._set_overall(
                    round(cur / tot * 100) if tot > 0 else 0,
                    f"Extracting ({cur}/{tot})",
                ),
            )
            try:
                if self.split_chapters.get() and doc_path.suffix.lower() in chapter_formats:
                    raw_chapters = DocumentExtractor.extract_chapters(
                        doc_path, self.chapter_level.get(),
                        from_page=from_page, to_page=to_page,
                    )
                    entries = []
                    for idx, (title, content) in enumerate(raw_chapters):
                        stripped = content.strip()
                        if not stripped:
                            continue
                        entry = ChapterEntry(
                            source_path=doc_path,
                            index=idx,
                            title=title,
                            content=stripped,
                            word_count=len(stripped.split()),
                        )
                        entries.append(entry)

                    entries = self._merge_short_chapters(entries)
                    for entry in entries:
                        self.extracted_texts[entry] = entry.content
                    self._chapter_entries[doc_path] = entries

                    if entries:
                        titles = [
                            f"{e.title[:40] if e.title else f'Ch{e.index+1}'}"
                            for e in entries
                        ]
                        status = f"{len(entries)} chapters: {', '.join(titles)}"
                    else:
                        status = "No chapters found"
                    self.window.after(
                        0,
                        lambda p=doc_path, s=status: self._update_doc_status(p, s),
                    )
                else:
                    text = DocumentExtractor.extract_text(doc_path, from_page=from_page, to_page=to_page)
                    entry = ChapterEntry(
                        source_path=doc_path,
                        index=0,
                        title="",
                        content=text,
                        word_count=len(text.split()),
                    )
                    self.extracted_texts[entry] = text
                    self._chapter_entries[doc_path] = [entry]
                    word_count = len(text.split())
                    self.window.after(
                        0,
                        lambda p=doc_path, wc=word_count: self._update_doc_status(
                            p, f"Extracted ({wc:,} words)"
                        ),
                    )
            except Exception as exc:
                self.window.after(
                    0,
                    lambda p=doc_path, e=str(exc): self._update_doc_status(p, f"Failed: {e}"),
                )

    def _do_preparation(self) -> None:
        entries = list(self.extracted_texts.keys())
        if not entries:
            raise RuntimeError("No documents could be extracted.")

        self.window.after(0, lambda: self.phase_text.set("Preparing text chunks..."))
        self.window.after(0, lambda: self._set_overall(0, "Preparing..."))

        self.chunk_counts: dict[ChapterEntry, int] = {}
        total_chunks = 0
        for i, entry in enumerate(entries):
            if self.stop_event.is_set():
                return
            text = self.extracted_texts[entry]
            count = len(chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK))
            self.chunk_counts[entry] = max(count, 1)
            total_chunks += self.chunk_counts[entry]
            self.window.after(
                0,
                lambda cur=i + 1, tot=len(entries): self._set_overall(
                    round(cur / tot * 10),
                    f"Preparing ({cur}/{tot})",
                ),
            )

        self._total_chunks = max(total_chunks, 1)

    def _build_request(self, text: str, output_path: Path) -> SynthesisRequest:
        piper_label = self.wizard_piper_voice_label.get().strip() or DEFAULT_PIPER_VOICE_LABEL
        voice_metadata = self.app.piper_voice_options.get(
            piper_label, get_piper_voice_metadata(piper_label)
        )
        return SynthesisRequest(
            text=text,
            language=self.app.language.get().strip() or "hu",
            output_file=output_path,
            engine=self.wizard_engine.get().strip() or ENGINE_AUTO,
            piper_voice_label=piper_label,
            piper_voice_code=voice_metadata["code"],
            speaker_name=self.wizard_speaker_name.get().strip() or DEFAULT_SPEAKER,
            speaker_wav=self.wizard_speaker_wav.get().strip(),
            speed=round(self.wizard_speed.get(), 1),
        )

    def _do_synthesis_per_file(self, output_folder: Path) -> None:
        entries = list(self.extracted_texts.keys())
        if not entries:
            raise RuntimeError("No documents with valid extracted text.")

        total_entries = len(entries)
        cumul_chunks = 0
        suffix = f".{self.output_format.get().lower()}"
        split_active = self.split_chapters.get()
        seen_docs: set[Path] = set()

        for i, entry in enumerate(entries):
            if self.stop_event.is_set():
                return

            source_path = entry.source_path
            if split_active and source_path not in seen_docs:
                seen_docs.add(source_path)
                all_entries = self._chapter_entries.get(source_path, [entry])
                self.window.after(
                    0,
                    lambda p=source_path: self._update_doc_status(p, "Synthesizing..."),
                )

            if split_active:
                chapter_label = f"ch {entry.index + 1}/{len(self._chapter_entries.get(source_path, [entry]))}"
                self.window.after(
                    0,
                    lambda cur=i + 1, tot=total_entries, lbl=chapter_label: self.phase_text.set(
                        f"Synthesizing {lbl} ({cur}/{tot})..."
                    ),
                )
            else:
                self.window.after(
                    0,
                    lambda cur=i + 1, tot=total_entries: self.phase_text.set(
                        f"Synthesizing document {cur}/{tot}..."
                    ),
                )

            output_path = self._chapter_output_path(entry, output_folder, suffix, split_active)

            text = self.extracted_texts[entry]
            expected = self.chunk_counts.get(entry, 1)
            self._synthesize_text(
                text,
                output_path,
                expected_chunks=expected,
                doc_index=i,
                total_docs=total_entries,
                cumul_chunks_start=cumul_chunks,
            )
            cumul_chunks += expected

            if self.stop_event.is_set():
                self.window.after(0, lambda p=source_path: self._update_doc_status(p, "Stopped"))
                return

            done_status = "Done"
            if split_active:
                all_entries = self._chapter_entries.get(source_path, [])
                last_in_doc = (entry.index == all_entries[-1].index) if all_entries else True
                if not last_in_doc:
                    continue
            self.window.after(0, lambda p=source_path, s=done_status: self._update_doc_status(p, s))

        self._finish(None)

    def _do_synthesis_merged(self, output_folder: Path) -> None:
        entries = list(self.extracted_texts.keys())
        if not entries:
            raise RuntimeError("No documents with valid extracted text.")

        parts: list[str] = []
        for entry in entries:
            if entry.title:
                parts.append(entry.title)
                parts.append(entry.content)
            else:
                parts.append(entry.content)

        merged_text = "\n\n".join(parts)
        total_expected = sum(self.chunk_counts.get(e, 1) for e in entries)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        suffix = f".{self.output_format.get().lower()}"
        output_path = output_folder / f"merged_{timestamp}{suffix}"

        self.window.after(0, lambda: self.phase_text.set("Synthesizing merged output..."))

        self._synthesize_text(
            merged_text,
            output_path,
            expected_chunks=total_expected,
            doc_index=0,
            total_docs=1,
            cumul_chunks_start=0,
        )

        if not self.stop_event.is_set():
            self._finish(None)

    def _chapter_output_path(
        self,
        entry: ChapterEntry,
        output_folder: Path,
        suffix: str,
        split_active: bool,
    ) -> Path:
        if split_active and entry.title:
            safe_title = sanitize_filename(entry.title)[:50]
            return output_folder / f"{entry.source_path.stem}__{safe_title}{suffix}"
        if split_active:
            return output_folder / f"{entry.source_path.stem}_ch{entry.index + 1:02d}{suffix}"
        return output_folder / f"{entry.source_path.stem}{suffix}"

    @staticmethod
    def _merge_short_chapters(
        entries: list[ChapterEntry],
        min_words: int = MIN_CHAPTER_WORDS,
    ) -> list[ChapterEntry]:
        if not entries:
            return entries

        merged: list[ChapterEntry] = []
        i = 0
        while i < len(entries):
            current = entries[i]
            if current.word_count >= min_words or len(merged) == 0:
                merged.append(current)
                i += 1
                continue

            prev = merged[-1]
            combined_title = f"{prev.title}; {current.title}" if current.title else prev.title
            combined_content = f"{prev.content}\n\n{current.content}"
            merged[-1] = ChapterEntry(
                source_path=prev.source_path,
                index=prev.index,
                title=combined_title,
                content=combined_content,
                word_count=prev.word_count + current.word_count,
            )
            i += 1

        if merged:
            for idx, entry in enumerate(merged):
                merged[idx] = ChapterEntry(
                    source_path=entry.source_path,
                    index=idx,
                    title=entry.title,
                    content=entry.content,
                    word_count=entry.word_count,
                )

        return merged

    def _synthesize_text(
        self,
        text: str,
        output_path: Path,
        expected_chunks: int,
        doc_index: int,
        total_docs: int,
        cumul_chunks_start: int,
    ) -> None:
        request = self._build_request(text, output_path)
        combined = AudioSegment.silent(duration=0)
        chunk_count = 0

        for _chunk, segment in self.app.service.iter_segments(request):
            if self.stop_event.is_set():
                return
            self.pause_event.wait()

            combined += segment
            chunk_count += 1
            if chunk_count < expected_chunks:
                combined += AudioSegment.silent(duration=PAUSE_MS)

            current = cumul_chunks_start + chunk_count
            total = max(self._total_chunks, 1)
            overall_pct = round(current / total * 100)
            file_pct = (
                round(chunk_count / expected_chunks * 100)
                if expected_chunks > 0
                else 0
            )
            self.window.after(
                0,
                lambda ov=overall_pct, msg=f"{current}/{total} chunks": self._set_overall(ov, msg),
            )
            self.window.after(
                0,
                lambda fp=file_pct, msg=f"Chunk {chunk_count}/{expected_chunks}": self._set_file(fp, msg),
            )
            self.window.after(
                0,
                lambda cur=doc_index + 1, tot=total_docs: self.phase_text.set(
                    f"Synthesizing document {cur}/{tot}..."
                ),
            )

        if self.stop_event.is_set():
            return

        quality = self.quality_preset.get()
        preset: dict = {}
        if self.output_format.get() == "OGG":
            preset = self.OGG_PRESETS.get(quality, {})
        elif self.output_format.get() == "MP3":
            preset = self.MP3_PRESETS.get(quality, {})

        self.window.after(0, lambda: self.phase_text.set("Exporting audio file..."))
        export_audio_segment(
            combined,
            output_path,
            bitrate=preset.get("bitrate"),
            quality_params=preset.get("quality_params"),
        )
        self.app.enqueue_log(f"Exported: {output_path}")

    def _toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button_text.set("Resume")
        else:
            self.pause_event.set()
            self.pause_button_text.set("Pause")

    def _stop_processing(self) -> None:
        self.stop_event.set()
        self.pause_event.set()
        self.pause_button_text.set("Pause")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Processing in progress",
                "A conversion job is running. Stop it and close?",
            ):
                return
            self._stop_processing()
            self.worker.join(timeout=3)
        self.window.destroy()

    def _update_doc_status(self, doc_path: Path, status: str) -> None:
        self.doc_status[doc_path] = status
        iid = str(doc_path)
        if self.tree.exists(iid):
            values = list(self.tree.item(iid, "values"))
            if len(values) >= 4:
                values[3] = status
                self.tree.item(iid, values=values)

    def _set_overall(self, value: int, text: str) -> None:
        self.overall_bar["value"] = value
        self.overall_text.set(text)

    def _set_file(self, value: int, text: str) -> None:
        self.file_bar["value"] = value
        self.file_text.set(text)

    def _finish(self, error: str | None) -> None:
        def apply() -> None:
            self._set_buttons_state(processing=False)
            if error:
                self.phase_text.set(error)
                self.overall_text.set("Failed")
            else:
                self.phase_text.set("Conversion complete.")
                self.overall_bar["value"] = 100
                self.overall_text.set("Done")
                self.file_bar["value"] = 100
                self.file_text.set("")
                self.app.enqueue_log("Document conversion complete.")
        self.window.after(0, apply)


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
        self.doc_wizard: DocumentToAudioWizard | None = None
        self.piper_voice_options = discover_local_piper_voices()

        self.language = StringVar(value="hu")
        self.engine = StringVar(value=ENGINE_AUTO)
        initial_piper_voice = self.settings.get("default_piper_voice_label", DEFAULT_PIPER_VOICE_LABEL)
        if initial_piper_voice not in self.piper_voice_options:
            initial_piper_voice = DEFAULT_PIPER_VOICE_LABEL
        self.piper_voice_label = StringVar(value=initial_piper_voice)
        self.speaker_name = StringVar(value=DEFAULT_SPEAKER)
        self.speaker_wav = StringVar()
        self.output_file = StringVar(value=str((get_default_music_folder() / "speech.mp3").resolve()))
        self.status = StringVar(value="Ready")
        self.playback_toggle_label = StringVar(value="Pause")
        self.speed = DoubleVar(value=1.0)
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

    def _configure_styles(self) -> None:  # pragma: no cover
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background=SURFACE_BG)
        style.configure("HeaderPanel.TFrame", background=CARD_BG)
        style.configure("Toolbar.TFrame", background=SURFACE_BG)
        style.configure("TLabel", background=SURFACE_BG)
        style.configure("Header.TLabel", background=CARD_BG, foreground="#101828", font=(FONT_BODY, 20, "bold"))
        style.configure("HeroIcon.TLabel", background=CARD_BG, foreground=ACCENT, font=(FONT_BODY, 22))
        style.configure("Subtle.TLabel", background=CARD_BG, foreground=MUTED_TEXT, font=(FONT_BODY, 10))
        style.configure("Hint.TLabel", background=SURFACE_BG, foreground=MUTED_TEXT, font=(FONT_BODY, 9))
        style.configure(
            "TLabelframe",
            background=CARD_BG,
            bordercolor=TEXT_BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=CARD_BG, foreground="#0f172a", font=(FONT_BODY, 10, "bold"))
        style.configure(
            "TButton",
            padding=(12, 8),
            font=(FONT_BODY, 9, "bold"),
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

    def _build_ui(self) -> None:  # pragma: no cover
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
            values=ENGINE_LANGUAGES[ENGINE_AUTO],
            state="readonly",
            width=12,
        )
        self.lang_box.grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(controls, text="Engine").grid(row=0, column=2, sticky="w", padx=(18, 10), pady=6)
        self.engine_box = ttk.Combobox(
            controls,
            textvariable=self.engine,
            values=[ENGINE_AUTO, ENGINE_PIPER, ENGINE_XTTS, ENGINE_POCKET],
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
        self.speaker_wav_button = ttk.Button(controls, text="Browse", command=self.pick_reference_wav)
        self.speaker_wav_button.grid(row=2, column=4, sticky="e", pady=6)

        ttk.Label(controls, text="Output file").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(controls, textvariable=self.output_file).grid(row=3, column=1, columnspan=3, sticky="ew", pady=6)
        ttk.Button(controls, text="Save As", command=self.pick_output_file).grid(row=3, column=4, sticky="e", pady=6)

        self.speed_label = ttk.Label(controls, text="Speed: 1.0x")
        self.speed_label.grid(row=4, column=0, sticky="w", padx=(0, 10), pady=6)
        self.speed_slider = ttk.Scale(
            controls,
            from_=0.5,
            to=2.0,
            variable=self.speed,
            orient="horizontal",
            command=self._on_speed_changed,
        )
        self.speed_slider.grid(row=4, column=1, columnspan=4, sticky="ew", pady=6)

        self.engine_hint = StringVar(value="")
        ttk.Label(controls, textvariable=self.engine_hint, style="Hint.TLabel").grid(
            row=5, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

        actions = ttk.Frame(main, style="Toolbar.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Load Text", command=self.load_text_file).pack(side="left")
        ttk.Button(actions, text="Convert Docs", command=self.open_document_wizard).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Voice Wizard", command=self.open_voice_wizard).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="▶ Read Aloud", style="Accent.TButton", command=self.start_read_aloud).pack(side="left", padx=(8, 0))
        self.playback_toggle_button = ttk.Button(
            actions,
            textvariable=self.playback_toggle_label,
            command=self.toggle_playback_pause,
        )
        self.playback_toggle_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="■ Stop", command=self.stop_playback).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Generate Audio", style="Accent.TButton", command=self.start_generation).pack(side="right")

        ttk.Label(main, text="Text").pack(anchor="w")
        self.textbox = ttk.Frame(main)
        self.textbox.pack(fill="both", expand=True)

        self.text = Text(
            self.textbox,
            wrap="word",
            font=(FONT_BODY, 11),
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
            font=(FONT_MONO, 10),
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
        pocket_enabled = resolved == ENGINE_POCKET

        resolved_langs = ENGINE_LANGUAGES.get(resolved, ENGINE_LANGUAGES[ENGINE_AUTO])
        self.lang_box.configure(values=resolved_langs)
        if self.language.get() not in resolved_langs:
            self.language.set(resolved_langs[0])

        speaker_state = "normal" if (xtts_enabled or pocket_enabled) else "disabled"
        self.speaker_name_entry.configure(state=speaker_state)
        self.speaker_wav_entry.configure(state=speaker_state)
        self.speaker_wav_button.configure(state=speaker_state)
        self.piper_voice_box.configure(state="readonly" if piper_enabled or self.engine.get() == ENGINE_AUTO else "disabled")

        if resolved == ENGINE_PIPER:
            self.engine_hint.set(
                f"Piper uses the local '{voice_metadata['code']}' voice. Adding a reference WAV switches Auto to XTTS."
            )
        elif resolved == ENGINE_POCKET:
            self.engine_hint.set(
                "Pocket TTS uses the Language field. Enter a built-in voice name "
                "(e.g. 'alba', 'anna') or point Reference WAV to a sample for voice cloning."
            )
        else:
            self.engine_hint.set(
                "XTTS uses the Language field plus built-in speakers or reference voice cloning. Piper voice selection is ignored."
            )

    def _on_speed_changed(self, *args) -> None:
        speed_val = round(self.speed.get(), 1)
        self.speed_label.configure(text=f"Speed: {speed_val:.1f}x")

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
            parent=self.root,
            title="Choose reference voice WAV",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac"), ("All files", "*.*")],
        )
        if path:
            self.speaker_wav.set(path)

    def pick_output_file(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
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

    def open_document_wizard(self) -> None:
        if self.doc_wizard is not None and self.doc_wizard.window.winfo_exists():
            self.doc_wizard.window.lift()
            self.doc_wizard.window.focus_force()
            return
        self.doc_wizard = DocumentToAudioWizard(self)

    def open_path_in_system(self, path: Path) -> None:  # pragma: no cover
        if sys.platform.startswith("win"):
            os.startfile(str(path))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    def show_generation_modal(self, output_path: Path) -> None:  # pragma: no cover
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
            parent=self.root,
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
            speed=round(self.speed.get(), 1),
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
            self.playback_toggle_label.set("Resume")
        else:
            self.playback_toggle_label.set("Pause")

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


if __name__ == "__main__":  # pragma: no cover
    main()
