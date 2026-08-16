"""Tests for format detection and the loader's dispatch to each converter."""

import pytest

from examrag.enums import DocumentType
from examrag.ingestion.document import DocumentLoadError, UnsupportedDocumentTypeError
from examrag.ingestion.document_loader import detect_document_type, load_document

from .conftest import BODY_SIZE, HEADING_SIZE


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("notes.pdf", DocumentType.PDF),
        ("Notes.PDF", DocumentType.PDF),
        ("paper.docx", DocumentType.DOCX),
        ("readme.md", DocumentType.MARKDOWN),
        ("readme.markdown", DocumentType.MARKDOWN),
        ("notes.txt", DocumentType.TXT),
        ("archive.2024.exam.pdf", DocumentType.PDF),
    ],
)
def test_detect_document_type(filename: str, expected: DocumentType) -> None:
    assert detect_document_type(filename) is expected


@pytest.mark.parametrize("filename", ["notes.doc", "slides.pptx", "data.csv", "noextension"])
def test_unsupported_types_are_rejected(filename: str) -> None:
    with pytest.raises(UnsupportedDocumentTypeError) as error:
        detect_document_type(filename)

    # The message should tell the user what is actually accepted.
    assert ".pdf" in str(error.value)


def test_markdown_is_passed_through_unchanged() -> None:
    source = "# OSI Model\n\nThe model has seven layers.\n\n- Physical\n- Data link\n"

    document = load_document("notes.md", source.encode())

    assert document.document_type is DocumentType.MARKDOWN
    assert document.markdown == source
    assert document.page_count == 1
    assert document.pages[0].number is None


def test_plain_text_is_treated_as_markdown() -> None:
    document = load_document("notes.txt", b"TCP provides reliable transport.")

    assert document.document_type is DocumentType.TXT
    assert document.markdown == "TCP provides reliable transport."


def test_a_utf8_bom_is_stripped() -> None:
    document = load_document("notes.md", "﻿# Heading".encode())

    assert document.markdown == "# Heading"


def test_cp1252_text_is_decoded() -> None:
    document = load_document("notes.txt", "Résumé — dash".encode("cp1252"))

    assert "Résumé" in document.markdown


def test_undecodable_bytes_raise_a_load_error() -> None:
    # Invalid UTF-8, and 0x81/0x8d/0x90 are undefined in CP-1252 as well.
    with pytest.raises(DocumentLoadError, match="not valid UTF-8"):
        load_document("notes.txt", b"\xff\xfe\x81\x8d\x90")


def test_empty_files_are_rejected() -> None:
    with pytest.raises(DocumentLoadError, match="empty"):
        load_document("notes.md", b"")


def test_pdf_bytes_are_routed_to_the_pdf_converter(make_pdf) -> None:
    data = make_pdf([[("Transport Layer", HEADING_SIZE), ("TCP is reliable.", BODY_SIZE)]])

    document = load_document("networking.pdf", data)

    assert document.document_type is DocumentType.PDF
    assert "# Transport Layer" in document.markdown


def test_docx_bytes_are_routed_to_the_docx_converter(make_docx) -> None:
    data = make_docx([("Transport Layer", "Heading 1"), ("TCP is reliable.", "")])

    document = load_document("networking.docx", data)

    assert document.document_type is DocumentType.DOCX
    assert "# Transport Layer" in document.markdown


def test_a_corrupt_pdf_raises_a_load_error() -> None:
    with pytest.raises(DocumentLoadError):
        load_document("broken.pdf", b"%PDF-1.7 this is not a real pdf")


def test_a_corrupt_docx_raises_a_load_error() -> None:
    with pytest.raises(DocumentLoadError):
        load_document("broken.docx", b"PK\x03\x04 not really a docx")


def test_markdown_joins_pages_and_skips_empty_ones(make_pdf) -> None:
    data = make_pdf(
        [
            [("Page one text.", BODY_SIZE)],
            [],  # a blank page, as produced by a section break
            [("Page three text.", BODY_SIZE)],
        ]
    )

    document = load_document("notes.pdf", data)

    assert document.page_count == 3
    assert document.markdown == "Page one text.\n\nPage three text."
