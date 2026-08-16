"""Tests for pulling individual questions out of stored chunk content."""

import uuid

from examrag.faq.question_extractor import SourceChunk, extract_questions

DOCUMENT_ID = uuid.uuid4()


def chunk(
    content: str, page_number: int | None = 1, heading: str | None = "Section A"
) -> SourceChunk:
    return SourceChunk(
        document_id=DOCUMENT_ID,
        filename="2023.pdf",
        content=content,
        page_number=page_number,
        heading=heading,
    )


def test_numbered_questions_are_split_by_marker() -> None:
    questions = extract_questions(
        [
            chunk(
                "1. Explain the OSI model in detail.\n2. Describe how TCP establishes a connection."
            )
        ]
    )

    assert [item.text for item in questions] == [
        "Explain the OSI model in detail.",
        "Describe how TCP establishes a connection.",
    ]


def test_a_question_mark_variant_is_recognised() -> None:
    questions = extract_questions([chunk("1) Explain the OSI model in seven layers.")])

    assert questions[0].text == "Explain the OSI model in seven layers."


def test_a_q_prefixed_marker_is_recognised() -> None:
    questions = extract_questions([chunk("Q1. What does the transport layer guarantee?")])

    assert questions[0].text == "What does the transport layer guarantee?"


def test_lettered_sub_parts_are_recognised() -> None:
    questions = extract_questions(
        [chunk("(a) Define a subnet mask.\n(b) Calculate the number of usable hosts in /24.")]
    )

    assert [item.text for item in questions] == [
        "Define a subnet mask.",
        "Calculate the number of usable hosts in /24.",
    ]


def test_continuation_lines_join_the_question_they_follow() -> None:
    questions = extract_questions(
        [
            chunk(
                "1. Explain the seven layers of the OSI model,\n"
                "covering the responsibility of each one. [10 marks]"
            )
        ]
    )

    assert len(questions) == 1
    assert questions[0].text == (
        "Explain the seven layers of the OSI model, covering the responsibility of each one. "
        "[10 marks]"
    )


def test_a_block_without_any_marker_yields_nothing() -> None:
    questions = extract_questions([chunk("Answer all questions in this section.")])

    assert questions == []


def test_a_stray_line_before_the_first_marker_is_dropped() -> None:
    questions = extract_questions([chunk("Section A\n1. Explain the OSI model in detail.")])

    assert len(questions) == 1
    assert questions[0].text == "Explain the OSI model in detail."


def test_short_marker_lines_are_filtered_as_labels_not_questions() -> None:
    questions = extract_questions([chunk("1. Section A")])

    assert questions == []


def test_questions_do_not_leak_across_a_blank_line_block_boundary() -> None:
    questions = extract_questions(
        [chunk("1. Explain the OSI model in detail.\n\n2. Describe TCP's three-way handshake.")]
    )

    assert len(questions) == 2


def test_questions_do_not_leak_across_chunks() -> None:
    questions = extract_questions(
        [
            chunk("1. Explain the OSI model in detail."),
            chunk("2. Describe TCP's three-way handshake in full."),
        ]
    )

    assert len(questions) == 2


def test_provenance_is_carried_through() -> None:
    questions = extract_questions(
        [chunk("1. Explain the OSI model in detail.", page_number=3, heading="Networking > Q1")]
    )

    assert questions[0].document_id == DOCUMENT_ID
    assert questions[0].filename == "2023.pdf"
    assert questions[0].page_number == 3
    assert questions[0].heading == "Networking > Q1"


def test_no_chunks_yields_no_questions() -> None:
    assert extract_questions([]) == []
