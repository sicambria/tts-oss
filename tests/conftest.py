from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="function")
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def docx_path(temp_dir: Path) -> Path:
    import docx

    path = temp_dir / "test.docx"
    doc = docx.Document()
    doc.add_paragraph("Hello world.")
    doc.add_paragraph("Second paragraph with more content.")
    doc.save(str(path))
    return path


@pytest.fixture
def docx_empty_path(temp_dir: Path) -> Path:
    import docx

    path = temp_dir / "empty.docx"
    doc = docx.Document()
    doc.save(str(path))
    return path


@pytest.fixture
def docx_corrupt_path(temp_dir: Path) -> Path:
    path = temp_dir / "corrupt.docx"
    path.write_bytes(b"this is not a valid zip file")
    return path


@pytest.fixture
def odt_path(temp_dir: Path) -> Path:
    from odf.opendocument import OpenDocumentText
    from odf.text import P

    path = temp_dir / "test.odt"
    doc = OpenDocumentText()
    doc.text.addElement(P(text="ODT paragraph one."))
    doc.text.addElement(P(text="ODT paragraph two."))
    doc.save(str(path))
    return path


@pytest.fixture
def odt_empty_path(temp_dir: Path) -> Path:
    from odf.opendocument import OpenDocumentText

    path = temp_dir / "empty.odt"
    doc = OpenDocumentText()
    doc.save(str(path))
    return path


@pytest.fixture
def epub_path(temp_dir: Path) -> Path:
    from ebooklib import epub

    path = temp_dir / "test.epub"
    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_identifier("test123")
    book.set_language("en")

    chap1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    chap1.content = "<h1>Chapter One</h1><p>This is chapter one content.</p>"
    book.add_item(chap1)

    chap2 = epub.EpubHtml(title="Chapter 2", file_name="chap2.xhtml", lang="en")
    chap2.content = "<h1>Chapter Two</h1><p>This is chapter two content.</p>"
    book.add_item(chap2)

    book.toc = (
        epub.Link("chap1.xhtml", "Chapter 1", "chap1"),
        epub.Link("chap2.xhtml", "Chapter 2", "chap2"),
    )
    book.spine = [chap1, chap2]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def epub_empty_path(temp_dir: Path) -> Path:
    from ebooklib import epub

    path = temp_dir / "empty.epub"
    book = epub.EpubBook()
    book.set_title("Empty Book")
    book.set_identifier("empty123")
    book.set_language("en")
    book.spine = []
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def pdf_empty_path(temp_dir: Path) -> Path:
    from pypdf import PdfWriter

    path = temp_dir / "empty.pdf"
    writer = PdfWriter()
    with open(str(path), "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def pdf_corrupt_path(temp_dir: Path) -> Path:
    path = temp_dir / "corrupt.pdf"
    path.write_bytes(b"this is not a valid pdf file")
    return path
