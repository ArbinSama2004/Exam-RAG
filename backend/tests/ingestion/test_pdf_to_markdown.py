"""Tests for PDF to Markdown conversion."""

import pytest

from examrag.ingestion.document import DocumentLoadError
from examrag.ingestion.pdf_to_markdown import convert_pdf_to_markdown

from .conftest import BODY_SIZE, HEADING_SIZE, SUBHEADING_SIZE


def test_page_numbers_start_at_one_and_are_preserved(make_pdf) -> None:
    data = make_pdf([[("First.", BODY_SIZE)], [("Second.", BODY_SIZE)]])

    pages = convert_pdf_to_markdown(data)

    assert [page.number for page in pages] == [1, 2]
    assert pages[1].markdown == "Second."


def test_larger_text_becomes_a_heading(make_pdf) -> None:
    data = make_pdf(
        [
            [
                ("The OSI Model", HEADING_SIZE),
                ("Physical Layer", SUBHEADING_SIZE),
                ("It transmits raw bits over a medium.", BODY_SIZE),
            ]
        ]
    )

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert "# The OSI Model" in markdown
    assert "## Physical Layer" in markdown
    assert "It transmits raw bits over a medium." in markdown


def test_heading_level_follows_relative_font_size(make_pdf) -> None:
    data = make_pdf(
        [
            [
                ("Huge Title", 30.0),
                ("Medium Section", 15.0),
                ("Small Section", 12.5),
                ("Body text that makes up the bulk of this page.", BODY_SIZE),
                ("More body text so the body size is unambiguous.", BODY_SIZE),
            ]
        ]
    )

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert "# Huge Title" in markdown
    assert "## Medium Section" in markdown
    assert "### Small Section" in markdown


def test_body_size_is_the_dominant_size_not_the_first_line(make_pdf) -> None:
    """A document that opens with a title must not treat the title as body text."""
    data = make_pdf(
        [
            [("Course Notes", HEADING_SIZE)]
            + [(f"Body sentence number {index}.", BODY_SIZE) for index in range(10)]
        ]
    )

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert markdown.startswith("# Course Notes")
    assert "# Body sentence" not in markdown


def test_bullet_glyphs_become_markdown_list_items(make_pdf) -> None:
    data = make_pdf(
        [
            [
                ("Layers of the model are listed below.", BODY_SIZE),
                ("• Physical", BODY_SIZE),
                ("• Data link", BODY_SIZE),
            ]
        ]
    )

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert "- Physical" in markdown
    assert "- Data link" in markdown
    assert "•" not in markdown


def test_a_page_with_no_text_produces_an_empty_page(make_pdf) -> None:
    data = make_pdf([[]])

    pages = convert_pdf_to_markdown(data)

    assert pages[0].is_empty
    assert pages[0].number == 1


def test_corrupt_bytes_raise_a_load_error() -> None:
    with pytest.raises(DocumentLoadError, match="Could not open the PDF"):
        convert_pdf_to_markdown(b"not a pdf at all")


def test_uniform_text_produces_no_headings(make_pdf) -> None:
    """A document with one font size is all body text, not all headings."""
    data = make_pdf([[(f"Sentence number {index}.", BODY_SIZE) for index in range(6)]])

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert "#" not in markdown


def test_a_short_bold_line_at_body_size_becomes_a_heading(make_pdf_bold) -> None:
    """Many documents mark sections with bold text rather than a larger font."""
    data = make_pdf_bold(
        bold_line="Transport Layer",
        body_lines=[f"Body sentence number {index}." for index in range(8)],
    )

    markdown = convert_pdf_to_markdown(data)[0].markdown

    assert "### Transport Layer" in markdown
    assert "# Body sentence" not in markdown
