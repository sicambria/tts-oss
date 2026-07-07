from __future__ import annotations

from app import (
    MAX_CHARS_PER_CHUNK,
    DocumentExtractor,
    chunk_text_with_offsets,
)


class TestFullPipeline:
    """End-to-end: extract text from real doc, then chunk it."""

    def test_docx_extract_then_chunk(self, docx_path) -> None:
        text = DocumentExtractor.extract_text(docx_path)
        chunks = chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK)
        assert len(chunks) > 0
        assert chunks[0].text.strip()
        assert "Hello world" in chunks[0].text

    def test_pdf_extract_then_chunk(self, pdf_empty_path) -> None:
        text = DocumentExtractor.extract_text(pdf_empty_path)
        chunks = chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK)
        assert isinstance(chunks, list)

    def test_odt_extract_then_chunk(self, odt_path) -> None:
        text = DocumentExtractor.extract_text(odt_path)
        chunks = chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK)
        assert len(chunks) > 0
        assert "ODT paragraph one" in chunks[0].text

    def test_epub_extract_then_chunk(self, epub_path) -> None:
        text = DocumentExtractor.extract_text(epub_path)
        chunks = chunk_text_with_offsets(text, MAX_CHARS_PER_CHUNK)
        assert len(chunks) > 0
        assert "Chapter One" in chunks[0].text

    def test_empty_input_returns_zero_chunks(self) -> None:
        chunks = chunk_text_with_offsets("", MAX_CHARS_PER_CHUNK)
        assert chunks == []
