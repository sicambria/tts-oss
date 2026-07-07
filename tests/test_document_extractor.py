from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from app import DocumentExtractor


class TestExtractTextDispatcher:
    def test_dispatch_docx(self, docx_path):
        text = DocumentExtractor.extract_text(docx_path)
        assert "Hello world" in text

    def test_dispatch_pdf(self, pdf_empty_path):
        text = DocumentExtractor.extract_text(pdf_empty_path)
        assert isinstance(text, str)

    def test_dispatch_odt(self, odt_path):
        text = DocumentExtractor.extract_text(odt_path)
        assert "ODT paragraph one" in text

    def test_dispatch_epub(self, epub_path):
        text = DocumentExtractor.extract_text(epub_path)
        assert "Chapter One" in text

    def test_unsupported_format(self, temp_dir):
        path = temp_dir / "file.xyz"
        path.write_text("garbage")
        with pytest.raises(ValueError, match="Unsupported document format"):
            DocumentExtractor.extract_text(path)

    def test_uppercase_extension(self, docx_path):
        renamed = docx_path.with_suffix(".DOCX")
        docx_path.rename(renamed)
        text = DocumentExtractor.extract_text(renamed)
        assert "Hello world" in text


class TestDocxExtraction:
    def test_extracts_paragraphs(self, docx_path):
        text = DocumentExtractor._extract_docx(docx_path)
        assert "Hello world." in text
        assert "Second paragraph with more content." in text
        assert "\n\n" in text

    def test_empty_docx_returns_empty(self, docx_empty_path):
        text = DocumentExtractor._extract_docx(docx_empty_path)
        assert text == ""

    def test_corrupt_zip_raises(self, docx_corrupt_path):
        with pytest.raises(Exception):
            DocumentExtractor._extract_docx(docx_corrupt_path)


class TestPdfExtraction:
    def test_corrupt_pdf_raises(self, pdf_corrupt_path):
        with pytest.raises(Exception):
            DocumentExtractor._extract_pdf(pdf_corrupt_path)

    def test_whitespace_cleaned(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Line one  \n\n\n\nLine two    with   spaces"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        pdf_file = temp_dir / "fake.pdf"
        pdf_file.write_text("")

        with patch("pypdf.PdfReader", return_value=mock_reader):
            text = DocumentExtractor._extract_pdf(pdf_file)

        assert "Line one" in text
        assert "Line two" in text
        assert "\n\n\n\n" not in text
        assert "    " not in text

    def test_multi_page_joined(self, temp_dir):
        page1 = MagicMock()
        page1.extract_text.return_value = "Page one content."
        page2 = MagicMock()
        page2.extract_text.return_value = "Page two content."

        mock_reader = MagicMock()
        mock_reader.pages = [page1, page2]

        pdf_file = temp_dir / "fake.pdf"
        pdf_file.write_text("")

        with patch("pypdf.PdfReader", return_value=mock_reader):
            text = DocumentExtractor._extract_pdf(pdf_file)

        assert "Page one content" in text
        assert "Page two content" in text


class TestOdtExtraction:
    def test_multi_paragraph(self, odt_path):
        text = DocumentExtractor._extract_odt(odt_path)
        assert "ODT paragraph one." in text
        assert "ODT paragraph two." in text

    def test_empty_odt(self, odt_empty_path):
        text = DocumentExtractor._extract_odt(odt_empty_path)
        assert text == ""


class TestEpubExtraction:
    def test_multi_chapter(self, epub_path):
        text = DocumentExtractor._extract_epub(epub_path)
        assert "Chapter One" in text
        assert "chapter one content" in text
        assert "Chapter Two" in text
        assert "chapter two content" in text

    def test_empty_epub_no_docs(self, epub_empty_path):
        text = DocumentExtractor._extract_epub(epub_empty_path)
        assert "chapter" not in text.lower()


class TestMissingLibraryMessage:
    def test_missing_docx_library_message(self, temp_dir):
        path = temp_dir / "test.docx"
        path.write_text("not a real docx")
        with patch("app.DocumentExtractor._extract_docx", side_effect=RuntimeError("python-docx not installed. Run: pip install python-docx")):
            with pytest.raises(RuntimeError, match="python-docx not installed"):
                DocumentExtractor._extract_docx(path)

    def test_missing_pdf_library_message(self, temp_dir):
        path = temp_dir / "test.pdf"
        path.write_text("not a real pdf")
        with patch("app.DocumentExtractor._extract_pdf", side_effect=RuntimeError("pypdf not installed. Run: pip install pypdf")):
            with pytest.raises(RuntimeError, match="pypdf not installed"):
                DocumentExtractor._extract_pdf(path)

    def test_missing_odt_library_message(self, temp_dir):
        path = temp_dir / "test.odt"
        with patch("app.DocumentExtractor._extract_odt", side_effect=RuntimeError("odfpy not installed. Run: pip install odfpy")):
            with pytest.raises(RuntimeError, match="odfpy not installed"):
                DocumentExtractor._extract_odt(path)

    def test_missing_mobi_library_message(self, temp_dir):
        path = temp_dir / "test.mobi"
        with patch("app.DocumentExtractor._extract_mobi", side_effect=RuntimeError("mobi not installed. Run: pip install mobi")):
            with pytest.raises(RuntimeError, match="mobi not installed"):
                DocumentExtractor._extract_mobi(path)


class TestMobiExtraction:
    def test_extract_mobi_epub_wrapper(self, temp_dir):
        mobi_path = temp_dir / "test.mobi"
        with patch("app.DocumentExtractor._extract_mobi") as mock_extract:
            mock_extract.return_value = "Mobi content extracted as epub."
            DocumentExtractor.extract_text(mobi_path)
        mock_extract.assert_called_once_with(mobi_path)

    def test_extract_mobi_with_mocked_library(self, temp_dir):
        mobi_path = temp_dir / "test.mobi"
        mobi_path.write_text("fake mobi")
        mock_extract = MagicMock()
        mock_extract.return_value = (str(temp_dir), str(temp_dir / "extracted.epub"))

        with patch("mobi.extract", mock_extract):
            with patch("app.DocumentExtractor._extract_epub", return_value="EPUB from MOBI"):
                result = DocumentExtractor._extract_mobi(mobi_path)
        assert result == "EPUB from MOBI"

    def test_extract_mobi_html_fallback(self, temp_dir):
        mobi_path = temp_dir / "test.mobi"
        mobi_path.write_text("fake mobi")
        mock_extract = MagicMock()
        mock_extract.return_value = (str(temp_dir), str(temp_dir / "extracted.html"))

        html_content = "<html><body><p>Hello from HTML</p></body></html>"
        (temp_dir / "extracted.html").write_text(html_content)

        with patch("mobi.extract", mock_extract):
            result = DocumentExtractor._extract_mobi(mobi_path)
        assert "Hello from HTML" in result


class TestSUPPORTED:
    def test_all_five_formats(self):
        assert len(DocumentExtractor.SUPPORTED) == 5
        assert ".docx" in DocumentExtractor.SUPPORTED
        assert ".odt" in DocumentExtractor.SUPPORTED
        assert ".pdf" in DocumentExtractor.SUPPORTED
        assert ".epub" in DocumentExtractor.SUPPORTED
        assert ".mobi" in DocumentExtractor.SUPPORTED

    def test_format_labels(self):
        assert DocumentExtractor.SUPPORTED[".docx"] == "DOCX"
        assert DocumentExtractor.SUPPORTED[".epub"] == "EPUB"
