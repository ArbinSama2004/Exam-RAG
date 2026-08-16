"""Tests for canonicalizing an extracted question's text."""

from examrag.faq.question_normalizer import normalize_question


def test_a_bracketed_mark_allocation_is_stripped() -> None:
    assert normalize_question("Explain the OSI model in detail. [10 marks]") == (
        "Explain the OSI model in detail."
    )


def test_a_parenthesized_point_allocation_is_stripped() -> None:
    assert normalize_question("Differentiate between TCP and UDP. (8 points)") == (
        "Differentiate between TCP and UDP."
    )


def test_a_bare_marks_suffix_is_stripped() -> None:
    assert normalize_question("Describe the three-way handshake. 5 marks") == (
        "Describe the three-way handshake."
    )


def test_curly_quotes_and_dashes_are_folded() -> None:
    assert normalize_question("What is DNS’s role — briefly?") == (  # noqa: RUF001
        "What is DNS's role - briefly?"
    )


def test_repeated_whitespace_is_collapsed() -> None:
    assert normalize_question("Explain   the OSI   model.") == "Explain the OSI model."


def test_a_plain_question_without_annotation_is_unchanged() -> None:
    assert normalize_question("What does the transport layer guarantee?") == (
        "What does the transport layer guarantee?"
    )


def test_trailing_stray_punctuation_is_trimmed() -> None:
    assert normalize_question("Explain the OSI model,") == "Explain the OSI model"
