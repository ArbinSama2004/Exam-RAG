"""Tests for assembling retrieved chunks into prompt context."""

import uuid

from examrag.rag.context_builder import build_context
from examrag.retrieval.base import RetrievedChunk


def chunk(content: str, rank: int = 1, **overrides) -> RetrievedChunk:
    defaults = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "filename": "notes.pdf",
        "content": content,
        "score": 0.9,
        "rank": rank,
    }
    return RetrievedChunk(**{**defaults, **overrides})


def test_passages_are_numbered_from_one() -> None:
    context = build_context([chunk("first"), chunk("second", 2)])

    assert [passage.number for passage in context.passages] == [1, 2]


def test_rendered_context_carries_numbers_and_sources() -> None:
    """The model can only cite a source it was shown."""
    context = build_context([chunk("TCP is reliable.", page_number=7, heading="Transport")])

    rendered = context.render()

    assert "[1]" in rendered
    assert "notes.pdf, p. 7 — Transport" in rendered
    assert "TCP is reliable." in rendered


def test_chunk_and_document_ids_are_preserved_for_traceability() -> None:
    original = chunk("text")

    passage = build_context([original]).passages[0]

    assert passage.chunk_id == str(original.chunk_id)
    assert passage.document_id == str(original.document_id)


def test_the_order_given_is_the_order_kept() -> None:
    """Chunks arrive best-first after reranking; reordering would undo that."""
    context = build_context([chunk("best"), chunk("second", 2), chunk("third", 3)])

    assert [passage.text for passage in context.passages] == ["best", "second", "third"]


def test_context_stops_at_the_character_budget() -> None:
    chunks = [chunk("x" * 400, rank=index) for index in range(1, 11)]

    context = build_context(chunks, max_chars=1000)

    assert 0 < len(context.passages) < 10


def test_the_least_relevant_passage_is_the_one_dropped() -> None:
    context = build_context(
        [chunk("keep", 1), chunk("y" * 5000, 2), chunk("drop", 3)], max_chars=1000
    )

    assert context.passages[0].text == "keep"
    assert "drop" not in [passage.text for passage in context.passages]


def test_one_oversized_chunk_is_still_included() -> None:
    """Returning no context at all would be worse than returning a long passage."""
    context = build_context([chunk("z" * 5000)], max_chars=1000)

    assert len(context.passages) == 1


def test_no_chunks_gives_an_empty_context() -> None:
    context = build_context([])

    assert context.is_empty
    assert context.render() == ""


def test_a_context_with_passages_is_not_empty() -> None:
    assert not build_context([chunk("text")]).is_empty
