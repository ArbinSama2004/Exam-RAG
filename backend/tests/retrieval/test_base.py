"""Tests for the shared retrieval types."""

import uuid

from examrag.enums import DocumentPurpose
from examrag.retrieval.base import RetrievalQuery, RetrievedChunk, rank_results


def chunk(**overrides) -> RetrievedChunk:
    defaults = {
        "chunk_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "filename": "notes.pdf",
        "content": "TCP is reliable.",
        "score": 0.9,
        "rank": 1,
    }
    return RetrievedChunk(**{**defaults, **overrides})


def test_source_includes_the_page_and_heading() -> None:
    assert chunk(page_number=7, heading="OSI Model").source == "notes.pdf, p. 7 — OSI Model"


def test_source_omits_a_missing_page() -> None:
    assert chunk(heading="OSI Model").source == "notes.pdf — OSI Model"


def test_source_is_just_the_filename_when_nothing_else_is_known() -> None:
    assert chunk().source == "notes.pdf"


def test_rank_results_numbers_from_one_in_order() -> None:
    ranked = rank_results([chunk(content="a", rank=0), chunk(content="b", rank=0)])

    assert [item.rank for item in ranked] == [1, 2]
    assert [item.content for item in ranked] == ["a", "b"]


def test_a_query_defaults_to_study_material() -> None:
    """Past papers must never be answer evidence unless asked for explicitly."""
    assert RetrievalQuery(text="TCP").purpose is DocumentPurpose.STUDY_MATERIAL


def test_a_query_can_target_past_papers_explicitly() -> None:
    query = RetrievalQuery(text="TCP", purpose=DocumentPurpose.PAST_PAPER)

    assert query.purpose is DocumentPurpose.PAST_PAPER
