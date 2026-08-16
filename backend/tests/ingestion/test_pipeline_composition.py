"""Load, clean and chunk a real PDF, checking the stages compose.

The individual modules are covered by their own tests; this verifies that what
one stage produces is what the next stage expects.
"""

from examrag.ingestion.chunker import MAX_CHUNK_CHARS, chunk_document
from examrag.ingestion.document_loader import load_document
from examrag.ingestion.markdown_cleaner import clean_document

from .conftest import BODY_SIZE, HEADING_SIZE, SUBHEADING_SIZE


def test_a_pdf_becomes_attributable_chunks(make_pdf) -> None:
    running_header = ("Computer Networks — Lecture Notes", BODY_SIZE)
    data = make_pdf(
        [
            [
                running_header,
                ("The OSI Model", HEADING_SIZE),
                ("Physical Layer", SUBHEADING_SIZE),
                ("It transmits raw bits over a phys-", BODY_SIZE),
                ("ical medium between two nodes.", BODY_SIZE),
                ("1", BODY_SIZE),
            ],
            [
                running_header,
                ("Transport Layer", SUBHEADING_SIZE),
                ("TCP provides reliable delivery.", BODY_SIZE),
                ("2", BODY_SIZE),
            ],
            [
                running_header,
                ("Network Layer", SUBHEADING_SIZE),
                ("IP routes packets between networks.", BODY_SIZE),
                ("3", BODY_SIZE),
            ],
        ]
    )

    document = clean_document(load_document("networking.pdf", data))
    chunks = chunk_document(document)

    assert chunks

    text = "\n".join(chunk.content for chunk in chunks)
    # The running header and the page numbers are artefacts, not content.
    assert "Lecture Notes" not in text
    assert "\n1\n" not in text
    # A word hyphenated across a line break is rejoined before embedding.
    assert "physical medium" in text
    assert "phys-" not in text

    headings = {chunk.heading for chunk in chunks}
    assert "The OSI Model > Physical Layer" in headings
    assert "The OSI Model > Transport Layer" in headings
    assert "The OSI Model > Network Layer" in headings

    # Every chunk stays traceable and within the size the schema expects.
    assert all(chunk.page_number in {1, 2, 3} for chunk in chunks)
    assert all(chunk.char_count <= MAX_CHUNK_CHARS for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_a_markdown_file_survives_the_pipeline_unchanged_in_meaning() -> None:
    source = "# Networking\n\n## TCP\n\nTCP is connection-oriented.\n\n- Reliable\n- Ordered\n"

    document = clean_document(load_document("notes.md", source.encode()))
    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].heading == "Networking > TCP"
    assert chunks[0].page_number is None
    assert "TCP is connection-oriented." in chunks[0].content
    assert "- Reliable" in chunks[0].content
