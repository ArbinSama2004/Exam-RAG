"""Tests for DOCX to Markdown conversion."""

import pytest

from examrag.ingestion.document import DocumentLoadError
from examrag.ingestion.docx_to_markdown import convert_docx_to_markdown


def convert(data: bytes) -> str:
    return convert_docx_to_markdown(data)[0].markdown


def test_heading_styles_map_to_heading_levels(make_docx) -> None:
    data = make_docx(
        [
            ("The OSI Model", "Heading 1"),
            ("Physical Layer", "Heading 2"),
            ("Cabling", "Heading 3"),
            ("It transmits raw bits.", ""),
        ]
    )

    markdown = convert(data)

    assert "# The OSI Model" in markdown
    assert "## Physical Layer" in markdown
    assert "### Cabling" in markdown
    assert "It transmits raw bits." in markdown


def test_title_and_subtitle_styles_map_to_headings(make_docx) -> None:
    markdown = convert(make_docx([("Networking", "Title"), ("An introduction", "Subtitle")]))

    assert "# Networking" in markdown
    assert "## An introduction" in markdown


def test_list_styles_map_to_markdown_lists(make_docx) -> None:
    markdown = convert(make_docx([("Physical", "List Bullet"), ("Data link", "List Bullet")]))

    assert markdown == "- Physical\n\n- Data link"


def test_numbered_lists_map_to_ordered_items(make_docx) -> None:
    markdown = convert(make_docx([("First step", "List Number")]))

    assert markdown == "1. First step"


def test_quotes_map_to_block_quotes(make_docx) -> None:
    markdown = convert(make_docx([("A network is a graph.", "Quote")]))

    assert markdown == "> A network is a graph."


def test_empty_paragraphs_are_dropped(make_docx) -> None:
    markdown = convert(make_docx([("Real text.", ""), ("   ", ""), ("More text.", "")]))

    assert markdown == "Real text.\n\nMore text."


def test_tables_become_markdown_tables(make_docx) -> None:
    markdown = convert(
        make_docx(
            [("Protocols", "Heading 1")],
            table=[["Protocol", "Layer"], ["TCP", "Transport"], ["IP", "Network"]],
        )
    )

    assert "| Protocol | Layer |" in markdown
    assert "| --- | --- |" in markdown
    assert "| TCP | Transport |" in markdown


def test_pipes_in_cells_are_escaped(make_docx) -> None:
    markdown = convert(make_docx([], table=[["a|b", "c"]]))

    assert r"a\|b" in markdown


def test_paragraphs_and_tables_keep_their_document_order(make_docx) -> None:
    """python-docx exposes them as separate collections; order must survive."""
    markdown = convert(make_docx([("Before the table.", "")], table=[["Protocol"], ["TCP"]]))

    assert markdown.index("Before the table.") < markdown.index("| Protocol |")


def test_docx_has_no_pagination(make_docx) -> None:
    pages = convert_docx_to_markdown(make_docx([("Text.", "")]))

    assert len(pages) == 1
    assert pages[0].number is None


def test_corrupt_bytes_raise_a_load_error() -> None:
    with pytest.raises(DocumentLoadError, match="Could not open the DOCX"):
        convert_docx_to_markdown(b"definitely not a docx")
