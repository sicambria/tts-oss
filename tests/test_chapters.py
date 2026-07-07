from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from app import ChapterEntry
from app import DocumentExtractor
from app import DocumentToAudioWizard
from app import sanitize_filename


class TestSanitizeFilename:
    def test_removes_illegal_chars(self):
        assert sanitize_filename('test:file"name') == "test_file_name"

    def test_strips_trailing_dots(self):
        assert sanitize_filename("hello...") == "hello"

    def test_preserves_valid_names(self):
        assert sanitize_filename("Chapter 1 - Introduction") == "Chapter 1 - Introduction"

    def test_replaces_slashes(self):
        assert sanitize_filename("a/b\\c") == "a_b_c"


class TestHeadingLevelHelpers:
    def test_detects_heading_1(self):
        assert DocumentExtractor._heading_level_from_style("Heading 1") == 1

    def test_detects_heading_2(self):
        assert DocumentExtractor._heading_level_from_style("Heading 3") == 3

    def test_detects_lowercase(self):
        assert DocumentExtractor._heading_level_from_style("heading 1") == 1

    def test_detects_no_space(self):
        assert DocumentExtractor._heading_level_from_style("Heading2") == 2

    def test_returns_none_for_non_heading(self):
        assert DocumentExtractor._heading_level_from_style("Normal") is None

    def test_returns_none_for_empty(self):
        assert DocumentExtractor._heading_level_from_style("") is None

    def test_returns_none_for_none(self):
        assert DocumentExtractor._heading_level_from_style(None) is None

    def test_level_for_setting_all(self):
        assert DocumentExtractor._heading_level_for_setting("all") is None

    def test_level_for_setting_h1(self):
        assert DocumentExtractor._heading_level_for_setting("h1") == 1

    def test_level_for_setting_h1_h2(self):
        assert DocumentExtractor._heading_level_for_setting("h1-h2") == 2

    def test_level_for_setting_h1_h3(self):
        assert DocumentExtractor._heading_level_for_setting("h1-h3") == 3

    def test_level_for_setting_unknown(self):
        assert DocumentExtractor._heading_level_for_setting("unknown") is None


class TestDocxChapterExtraction:
    def test_extracts_chapters_with_headings(self, docx_chapters_path):
        chapters = DocumentExtractor._extract_docx_chapters(docx_chapters_path)
        assert len(chapters) == 4
        titles = [c[0] for c in chapters]
        assert titles[0] == "Introduction"
        assert titles[1] == "Methods"
        assert titles[2] == "A subsection"
        assert titles[3] == "Results"
        assert "introduction text" in chapters[0][1].lower()

    def test_no_headings_falls_back_to_single_chapter(self, docx_no_headings_path):
        chapters = DocumentExtractor._extract_docx_chapters(docx_no_headings_path)
        assert len(chapters) == 1
        assert chapters[0][0] == ""
        assert "Just a paragraph" in chapters[0][1]

    def test_level_filter_h1_only(self, docx_chapters_path):
        chapters = DocumentExtractor._extract_docx_chapters(docx_chapters_path, min_level="h1")
        titles = [c[0] for c in chapters]
        assert "A subsection" not in titles
        assert "Introduction" in titles
        assert "Methods" in titles
        assert "Results" in titles

    def test_level_filter_h1_h2(self, docx_chapters_path):
        chapters = DocumentExtractor._extract_docx_chapters(docx_chapters_path, min_level="h1-h2")
        titles = [c[0] for c in chapters]
        assert "A subsection" in titles

    def test_empty_docx(self, docx_empty_path):
        chapters = DocumentExtractor._extract_docx_chapters(docx_empty_path)
        assert len(chapters) == 1
        assert chapters[0][0] == ""
        assert chapters[0][1] == ""


class TestOdtChapterExtraction:
    def test_extracts_chapters(self, odt_chapters_path):
        chapters = DocumentExtractor._extract_odt_chapters(odt_chapters_path)
        assert len(chapters) == 2
        assert chapters[0][0] == "Introduction"
        assert "Introduction text goes here" in chapters[0][1]
        assert chapters[1][0] == "Methods"

    def test_no_headings_falls_back(self, odt_empty_path):
        chapters = DocumentExtractor._extract_odt_chapters(odt_empty_path)
        assert len(chapters) == 1
        assert chapters[0][0] == ""


class TestEpubChapterExtraction:
    def test_extracts_chapters(self, epub_chapters_path):
        chapters = DocumentExtractor._extract_epub_chapters(epub_chapters_path)
        assert len(chapters) >= 1

    def test_no_headings_falls_back(self, epub_empty_path):
        chapters = DocumentExtractor._extract_epub_chapters(epub_empty_path)
        assert len(chapters) == 1
        assert chapters[0][0] == ""


class TestPdfChapterExtraction:
    def test_pattern_split(self, temp_dir):
        text = "Chapter 1\n\nThis is intro text.\n\nChapter 2\n\nThis is body text.\n\nChapter 3\n\nFinal chapter."
        pdf_path = temp_dir / "chapters.pdf"

        mock_page = MagicMock()
        mock_page.extract_text.return_value = text
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.outline = []

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_by_pattern(pdf_path)

        assert len(chapters) == 3
        assert "intro text" in chapters[0][1].lower()
        assert "body text" in chapters[1][1].lower()
        assert "Final chapter" in chapters[2][1]

    def test_no_headings_single_chapter(self, temp_dir):
        text = "Just some text without any headings."
        pdf_path = temp_dir / "no_chapters.pdf"

        mock_page = MagicMock()
        mock_page.extract_text.return_value = text
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.outline = []

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_by_pattern(pdf_path)

        assert len(chapters) == 1
        assert chapters[0][0] == ""


class TestExtractChaptersDispatcher:
    def test_docx(self, docx_chapters_path):
        chapters = DocumentExtractor.extract_chapters(docx_chapters_path)
        assert len(chapters) >= 1

    def test_pdf(self, pdf_empty_path):
        chapters = DocumentExtractor.extract_chapters(pdf_empty_path)
        assert len(chapters) >= 1

    def test_odt(self, odt_chapters_path):
        chapters = DocumentExtractor.extract_chapters(odt_chapters_path)
        assert len(chapters) >= 1

    def test_epub(self, epub_chapters_path):
        chapters = DocumentExtractor.extract_chapters(epub_chapters_path)
        assert len(chapters) >= 1


class TestChapterOutputPath:
    def test_no_split_uses_stem(self):
        entry = ChapterEntry(
            source_path=Path("/docs/report.docx"),
            index=0,
            title="",
            content="text",
            word_count=1,
        )
        result = DocumentToAudioWizard._chapter_output_path(
            MagicMock(), entry, Path("/out"), ".mp3", False
        )
        assert result == Path("/out/report.mp3")

    def test_split_with_title(self):
        entry = ChapterEntry(
            source_path=Path("/docs/report.docx"),
            index=0,
            title="Introduction",
            content="text",
            word_count=50,
        )
        result = DocumentToAudioWizard._chapter_output_path(
            MagicMock(), entry, Path("/out"), ".mp3", True
        )
        assert result.name.startswith("report__")
        assert "Introduction" in result.name
        assert result.suffix == ".mp3"

    def test_split_without_title(self):
        entry = ChapterEntry(
            source_path=Path("/docs/report.docx"),
            index=2,
            title="",
            content="text",
            word_count=50,
        )
        result = DocumentToAudioWizard._chapter_output_path(
            MagicMock(), entry, Path("/out"), ".mp3", True
        )
        assert result == Path("/out/report_ch03.mp3")


class TestMergeShortChapters:
    def _entry(self, content, title="", word_count=None):
        return ChapterEntry(
            source_path=Path("/test.docx"),
            index=0,
            title=title,
            content=content,
            word_count=word_count if word_count is not None else len(content.split()),
        )

    def test_no_merge_when_all_large(self):
        entries = [
            self._entry("a " * 50, word_count=50),
            self._entry("b " * 50, word_count=50),
        ]
        result = DocumentToAudioWizard._merge_short_chapters(entries)
        assert len(result) == 2
        assert result[0].index == 0
        assert result[1].index == 1

    def test_merges_short_into_previous(self):
        entries = [
            self._entry("a " * 50, title="Big", word_count=50),
            self._entry("tiny", title="Tiny", word_count=1),
        ]
        result = DocumentToAudioWizard._merge_short_chapters(entries)
        assert len(result) == 1
        assert "Tiny" in result[0].title
        assert "tiny" in result[0].content

    def test_merges_multiple_short(self):
        entries = [
            self._entry("a " * 50, title="First", word_count=50),
            self._entry("tiny1", title="T1", word_count=1),
            self._entry("tiny2", title="T2", word_count=2),
            self._entry("b " * 50, title="Last", word_count=50),
        ]
        result = DocumentToAudioWizard._merge_short_chapters(entries)
        assert len(result) == 2
        assert result[0].index == 0
        assert result[1].index == 1
        assert "tiny1" in result[0].content

    def test_empty_list(self):
        result = DocumentToAudioWizard._merge_short_chapters([])
        assert result == []

    def test_single_entry(self):
        entries = [self._entry("hello", word_count=1)]
        result = DocumentToAudioWizard._merge_short_chapters(entries)
        assert len(result) == 1


class TestPdfChapterFromOutline:
    def test_outline_extracts_chapters(self, temp_dir):
        text = "This is the intro text that covers multiple lines.\n\nMore intro content here."

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = text

        outline_item = MagicMock()
        outline_item.title = "Introduction"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page1]
        mock_reader.outline = [outline_item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(mock_reader)

        assert len(chapters) == 1
        assert chapters[0][0] == "Introduction"
        assert "intro text" in chapters[0][1].lower()

    def test_outline_with_nested_items(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Content here."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        child_item = MagicMock()
        child_item.title = "Subsection"
        mock_reader.outline = [[child_item]]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(mock_reader)

        assert len(chapters) >= 1

    def test_outline_no_items_returns_empty(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.outline = []

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(mock_reader)

        assert chapters == []

    def test_outline_title_stripped(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        item = MagicMock()
        item.title = "  Chapter 1  "
        mock_reader.outline = [item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(mock_reader)

        assert chapters[0][0] == "Chapter 1"

    def test_outline_skips_empty_title(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        item = MagicMock()
        item.title = ""
        mock_reader.outline = [item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_from_outline(mock_reader)

        assert chapters == []

    def test_extract_pdf_chapters_uses_outline(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Content text."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        item = MagicMock()
        item.title = "Chapter 1"
        mock_reader.outline = [item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters(temp_dir / "test.pdf")

        assert len(chapters) >= 1

    def test_extract_pdf_chapters_with_page_range(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page, mock_page, mock_page]

        item = MagicMock()
        item.title = "Chapter 1"
        mock_reader.outline = [item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters(
                temp_dir / "test.pdf", from_page=1, to_page=2
            )

        assert len(chapters) >= 1

    def test_extract_pdf_chapters_insufficient_outline_falls_back(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Just some content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        item = MagicMock()
        item.title = "Only Chapter"
        mock_reader.outline = [item]
        mock_reader.get_destination_page_number.return_value = 0

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters(temp_dir / "test.pdf")

        assert len(chapters) >= 1

    def test_pdf_chapters_empty_text_fallback(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.outline = []

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_by_pattern(temp_dir / "test.pdf")

        assert len(chapters) == 1
        assert chapters[0][0] == ""

    def test_pdf_chapters_no_pattern_match_falls_back(self, temp_dir):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Plain text without any chapter headings at all anywhere."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader.outline = []

        with patch("pypdf.PdfReader", return_value=mock_reader):
            chapters = DocumentExtractor._extract_pdf_chapters_by_pattern(temp_dir / "test.pdf")

        assert len(chapters) == 1
        assert "Plain text" in chapters[0][1]


class TestDocumentToAudioWizardFinish:
    def test_finish_success(self):
        wizard = DocumentToAudioWizard.__new__(DocumentToAudioWizard)
        wizard.window = MagicMock()
        wizard.window.after.side_effect = lambda ms, cb: cb()
        wizard._set_buttons_state = MagicMock()
        wizard.phase_text = MagicMock()
        wizard.overall_bar = MagicMock()
        wizard.overall_bar.__setitem__ = MagicMock()
        wizard.overall_text = MagicMock()
        wizard.file_bar = MagicMock()
        wizard.file_bar.__setitem__ = MagicMock()
        wizard.file_text = MagicMock()
        wizard.app = MagicMock()

        wizard._finish(None)
        wizard._set_buttons_state.assert_called_once_with(processing=False)
        wizard.phase_text.set.assert_called_with("Conversion complete.")
        wizard.app.enqueue_log.assert_called_once_with("Document conversion complete.")

    def test_finish_error(self):
        wizard = DocumentToAudioWizard.__new__(DocumentToAudioWizard)
        wizard.window = MagicMock()
        wizard.window.after.side_effect = lambda ms, cb: cb()
        wizard._set_buttons_state = MagicMock()
        wizard.phase_text = MagicMock()
        wizard.overall_text = MagicMock()
        wizard.app = MagicMock()

        wizard._finish("Something went wrong")
        wizard.phase_text.set.assert_called_with("Something went wrong")
        wizard.overall_text.set.assert_called_with("Failed")
