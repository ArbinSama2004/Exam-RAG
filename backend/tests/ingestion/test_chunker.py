"""Tests for structure-aware chunking."""

from examrag.enums import DocumentType
from examrag.ingestion.chunker import (
    CHUNKER_VERSION,
    MAX_CHUNK_CHARS,
    TARGET_CHUNK_CHARS,
    chunk_document,
)
from examrag.ingestion.document import DocumentPage, LoadedDocument


def make_document(*pages: tuple[str, int | None]) -> LoadedDocument:
    return LoadedDocument(
        filename="notes.pdf",
        document_type=DocumentType.PDF,
        pages=[DocumentPage(markdown=markdown, number=number) for markdown, number in pages],
    )


def paragraph(marker: str, length: int = 400) -> str:
    """A paragraph of roughly `length` characters, identifiable by `marker`."""
    sentence = f"This is {marker} content that fills the paragraph. "
    return (sentence * (length // len(sentence) + 1))[:length].strip()


def test_a_short_document_becomes_one_chunk() -> None:
    document = make_document(("TCP provides reliable transport.", 1))

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].content == "TCP provides reliable transport."
    assert chunks[0].index == 0


def test_chunk_indexes_are_sequential_from_zero() -> None:
    document = make_document(("\n\n".join(paragraph(str(n)) for n in range(12)), 1))

    chunks = chunk_document(document)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert len(chunks) > 1


def test_headings_start_a_new_chunk() -> None:
    document = make_document(
        ("# Transport Layer\n\nTCP is reliable.\n\n# Network Layer\n\nIP routes packets.", 1)
    )

    chunks = chunk_document(document)

    assert len(chunks) == 2
    assert "TCP is reliable." in chunks[0].content
    assert "IP routes packets." in chunks[1].content
    # A section's content must not leak into the previous chunk.
    assert "IP routes packets." not in chunks[0].content


def test_heading_is_recorded_as_a_breadcrumb() -> None:
    document = make_document(
        ("# OSI Model\n\n## Physical Layer\n\nIt transmits raw bits over a medium.", 1)
    )

    chunks = chunk_document(document)

    assert chunks[-1].heading == "OSI Model > Physical Layer"


def test_breadcrumb_drops_deeper_headings_when_a_section_ends() -> None:
    document = make_document(
        (
            "# OSI Model\n\n## Physical Layer\n\nBits.\n\n"
            "## Transport Layer\n\nSegments.\n\n"
            "# TCP/IP\n\nFour layers.",
            1,
        )
    )

    headings = [chunk.heading for chunk in chunk_document(document)]

    assert "OSI Model > Transport Layer" in headings
    assert "TCP/IP" in headings
    # The sibling section must not remain on the path.
    assert not any(heading and "Physical Layer > Transport" in heading for heading in headings)


def test_content_before_any_heading_has_no_breadcrumb() -> None:
    chunks = chunk_document(make_document(("Introductory text with no heading.", 1)))

    assert chunks[0].heading is None


def test_page_number_records_where_the_chunk_starts() -> None:
    document = make_document(("First page text.", 1), ("Second page text.", 2))

    chunks = chunk_document(document)

    assert chunks[0].page_number == 1
    assert all(chunk.page_number in (1, 2) for chunk in chunks)


def test_unpaginated_documents_have_no_page_number() -> None:
    document = LoadedDocument(
        filename="notes.md",
        document_type=DocumentType.MARKDOWN,
        pages=[DocumentPage(markdown="Some text.", number=None)],
    )

    assert chunk_document(document)[0].page_number is None


def test_long_content_is_split_into_several_chunks() -> None:
    document = make_document(("\n\n".join(paragraph(str(n)) for n in range(10)), 1))

    chunks = chunk_document(document)

    assert len(chunks) > 1
    assert all(chunk.char_count <= MAX_CHUNK_CHARS for chunk in chunks)


def test_a_single_oversized_paragraph_is_split_on_sentences() -> None:
    document = make_document((paragraph("long", MAX_CHUNK_CHARS * 2), 1))

    chunks = chunk_document(document)

    assert len(chunks) > 1
    assert all(chunk.char_count <= MAX_CHUNK_CHARS for chunk in chunks)
    # Splitting on sentence boundaries should not cut mid-word.
    assert all(not chunk.content.startswith(" ") for chunk in chunks)


def test_text_without_sentence_punctuation_is_still_split() -> None:
    document = make_document(("word " * (MAX_CHUNK_CHARS // 2), 1))

    chunks = chunk_document(document)

    assert all(chunk.char_count <= MAX_CHUNK_CHARS for chunk in chunks)


def test_consecutive_chunks_overlap() -> None:
    """A sentence split across a boundary should survive intact somewhere."""
    document = make_document(("\n\n".join(paragraph(str(n)) for n in range(8)), 1))

    chunks = chunk_document(document)

    assert len(chunks) > 1
    tail = chunks[0].content[-40:]
    assert tail.strip() and tail.strip() in chunks[1].content


def test_short_trailing_content_is_merged_into_its_neighbour() -> None:
    document = make_document((f"{paragraph('main', TARGET_CHUNK_CHARS - 100)}\n\nShort tail.", 1))

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert "Short tail." in chunks[0].content


def test_short_content_is_not_merged_across_a_heading() -> None:
    """Merging would file the text under the previous section's heading."""
    document = make_document(("# First\n\nShort one.\n\n# Second\n\nShort two.", 1))

    chunks = chunk_document(document)

    assert len(chunks) == 2
    assert chunks[0].heading == "First"
    assert chunks[1].heading == "Second"


def test_empty_pages_contribute_nothing() -> None:
    document = make_document(("Real content.", 1), ("", 2), ("   \n\n  ", 3))

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].content == "Real content."


def test_an_empty_document_produces_no_chunks() -> None:
    assert chunk_document(make_document(("", 1))) == []


def test_char_count_matches_the_content() -> None:
    for chunk in chunk_document(make_document(("Some text here.", 1))):
        assert chunk.char_count == len(chunk.content)


def test_chunker_version_is_recorded() -> None:
    """The version is stored per document so stale chunks stay detectable."""
    assert CHUNKER_VERSION == "markdown-v1"


def test_a_heading_followed_by_a_subheading_does_not_become_its_own_chunk() -> None:
    """A chunk holding only a title carries no information worth embedding."""
    document = make_document(("# Networking\n\n## TCP\n\nTCP is connection-oriented.", 1))

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].heading == "Networking > TCP"
    assert "# Networking" in chunks[0].content
    assert "TCP is connection-oriented." in chunks[0].content


def test_a_trailing_heading_with_no_content_is_still_emitted() -> None:
    """It is the only record that the section exists."""
    document = make_document(("# First\n\nContent here.\n\n# Dangling", 1))

    chunks = chunk_document(document)

    assert chunks[-1].content == "# Dangling"
    assert chunks[-1].heading == "Dangling"
