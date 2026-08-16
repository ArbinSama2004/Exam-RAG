"""Tests for Markdown cleaning."""

from examrag.enums import DocumentType
from examrag.ingestion.document import DocumentPage, LoadedDocument
from examrag.ingestion.markdown_cleaner import clean_document, clean_markdown


def make_document(*page_markdown: str) -> LoadedDocument:
    return LoadedDocument(
        filename="notes.pdf",
        document_type=DocumentType.PDF,
        pages=[
            DocumentPage(markdown=markdown, number=number)
            for number, markdown in enumerate(page_markdown, start=1)
        ],
    )


def test_windows_and_mac_line_endings_are_normalized() -> None:
    assert clean_markdown("- first\r\n- second\r- third") == "- first\n- second\n- third"


def test_words_hyphenated_across_line_breaks_are_rejoined() -> None:
    """PDF justification splits words; embedding "net" and "work" loses meaning."""
    assert clean_markdown("A net-\nwork is a graph.") == "A network is a graph."


def test_runs_of_spaces_inside_a_line_are_collapsed() -> None:
    assert clean_markdown("TCP    provides     transport") == "TCP provides transport"


def test_list_indentation_is_preserved() -> None:
    source = "- Physical\n    - Cabling"

    assert clean_markdown(source) == source


def test_repeated_blank_lines_are_collapsed() -> None:
    assert clean_markdown("First.\n\n\n\n\nSecond.") == "First.\n\nSecond."


def test_page_number_lines_are_removed() -> None:
    cleaned = clean_markdown("Content here.\n\n7\n\nMore content.")

    assert "7" not in cleaned
    assert "Content here." in cleaned
    assert "More content." in cleaned


def test_various_page_marker_formats_are_removed() -> None:
    for marker in ("12", "Page 12", "page 12 of 30", "12 / 30"):
        assert clean_markdown(f"Text.\n\n{marker}\n\nMore.") == "Text.\n\nMore."


def test_a_number_inside_a_sentence_is_kept() -> None:
    assert "7 layers" in clean_markdown("The model has 7 layers.")


def test_non_breaking_spaces_become_ordinary_spaces() -> None:
    assert clean_markdown("TCP is reliable") == "TCP is reliable"  # noqa: RUF001


def test_control_characters_are_removed() -> None:
    assert clean_markdown("clean\x00text\x07here") == "cleantexthere"


def test_code_fences_are_left_untouched() -> None:
    """Whitespace is significant inside code, so cleaning must skip it."""
    source = "Example:\n\n```python\ndef f():\n    return    1\n```"

    cleaned = clean_markdown(source)

    assert "    return    1" in cleaned


def test_running_headers_are_removed_across_pages() -> None:
    document = make_document(
        "Computer Networks\n\nFirst page content.",
        "Computer Networks\n\nSecond page content.",
        "Computer Networks\n\nThird page content.",
        "Computer Networks\n\nFourth page content.",
    )

    cleaned = clean_document(document)

    assert "Computer Networks" not in cleaned.markdown
    assert "First page content." in cleaned.markdown
    assert "Fourth page content." in cleaned.markdown


def test_running_footers_are_removed_across_pages() -> None:
    document = make_document(*(f"Body {index}.\n\nCopyright 2024 University" for index in range(4)))

    assert "Copyright" not in clean_document(document).markdown


def test_repeat_detection_needs_enough_pages() -> None:
    """Two pages are not evidence that a shared line is a header."""
    document = make_document("Shared Title\n\nOne.", "Shared Title\n\nTwo.")

    assert "Shared Title" in clean_document(document).markdown


def test_content_repeated_mid_page_is_kept() -> None:
    """Only lines pinned to a page edge are treated as headers."""
    document = make_document(
        *(
            f"Opening line {index}.\n\nTCP is reliable.\n\nClosing line {index}."
            for index in range(4)
        )
    )

    assert clean_document(document).markdown.count("TCP is reliable.") == 4


def test_cleaning_preserves_page_numbers_and_type() -> None:
    cleaned = clean_document(make_document("One.", "Two."))

    assert [page.number for page in cleaned.pages] == [1, 2]
    assert cleaned.document_type is DocumentType.PDF
    assert cleaned.filename == "notes.pdf"


def test_leading_and_trailing_whitespace_is_stripped() -> None:
    assert clean_markdown("\n\n  Content.  \n\n") == "Content."


def test_prose_wrapped_across_lines_is_reflowed() -> None:
    """A converted PDF breaks paragraphs where the page did, not where the author did."""
    source = "TCP provides reliable,\nconnection-oriented transport\nbetween two hosts."

    assert clean_markdown(source) == (
        "TCP provides reliable, connection-oriented transport between two hosts."
    )


def test_list_items_keep_their_own_lines() -> None:
    assert clean_markdown("- Physical\n- Data link\n- Network") == (
        "- Physical\n- Data link\n- Network"
    )


def test_numbered_list_items_keep_their_own_lines() -> None:
    assert clean_markdown("1. First\n2. Second") == "1. First\n2. Second"


def test_headings_are_not_folded_into_the_next_paragraph() -> None:
    assert clean_markdown("# Transport\nTCP is reliable.") == "# Transport\nTCP is reliable."


def test_table_rows_keep_their_own_lines() -> None:
    source = "| Protocol | Layer |\n| --- | --- |\n| TCP | Transport |"

    assert clean_markdown(source) == source


def test_paragraph_breaks_survive_reflow() -> None:
    assert clean_markdown("First\nparagraph.\n\nSecond\nparagraph.") == (
        "First paragraph.\n\nSecond paragraph."
    )


def test_hyphenated_words_are_rejoined_across_a_blank_line() -> None:
    """PDF extraction often puts the two halves in separate text blocks."""
    assert clean_markdown("a phys-\n\nical medium") == "a physical medium"


def test_a_dash_before_a_list_item_is_not_treated_as_hyphenation() -> None:
    cleaned = clean_markdown("Consider the following-\n\n- Physical\n- Data link")

    assert "- Physical" in cleaned
    assert "following-" in cleaned
