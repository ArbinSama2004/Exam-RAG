"""Tests for cross-encoder reranking."""

import uuid

import pytest

from examrag.retrieval.base import RetrievedChunk
from examrag.retrieval.reranker import CrossEncoderReranker, RerankerError


class FakeCrossEncoder:
    """Scores each pair by a lookup on the chunk text."""

    def __init__(self, scores: dict[str, float] | None = None, fail: bool = False) -> None:
        self.scores = scores or {}
        self.fail = fail
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, sentences, batch_size: int = 16):
        if self.fail:
            raise RuntimeError("model unavailable")
        self.calls.append(list(sentences))
        return [self.scores.get(text, 0.0) for _, text in sentences]


class WrongLengthEncoder(FakeCrossEncoder):
    def predict(self, sentences, batch_size: int = 16):
        return [0.0]


def chunk(content: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, content),
        document_id=uuid.uuid4(),
        filename="notes.pdf",
        content=content,
        score=0.5,
        rank=rank,
    )


def test_candidates_are_reordered_by_relevance() -> None:
    """Reranking exists to overturn the fused order, not confirm it."""
    model = FakeCrossEncoder({"relevant": 9.0, "irrelevant": -3.0})
    reranker = CrossEncoderReranker(model=model)

    result = reranker.rerank("query", [chunk("irrelevant", 1), chunk("relevant", 2)], top_k=2)

    assert [item.content for item in result] == ["relevant", "irrelevant"]


def test_ranks_and_scores_are_replaced() -> None:
    model = FakeCrossEncoder({"a": 5.0, "b": 1.0})

    result = CrossEncoderReranker(model=model).rerank("q", [chunk("a", 3), chunk("b", 7)], 2)

    assert [item.rank for item in result] == [1, 2]
    assert result[0].score == 5.0


def test_only_top_k_are_returned() -> None:
    model = FakeCrossEncoder({"a": 3.0, "b": 2.0, "c": 1.0})
    chunks = [chunk("a", 1), chunk("b", 2), chunk("c", 3)]

    assert len(CrossEncoderReranker(model=model).rerank("q", chunks, top_k=2)) == 2


def test_the_query_is_paired_with_every_chunk() -> None:
    model = FakeCrossEncoder()

    CrossEncoderReranker(model=model).rerank("what is TCP?", [chunk("a", 1), chunk("b", 2)], 2)

    assert model.calls[0] == [("what is TCP?", "a"), ("what is TCP?", "b")]


def test_no_candidates_needs_no_model() -> None:
    assert CrossEncoderReranker().rerank("q", [], top_k=5) == []


def test_a_zero_top_k_returns_nothing() -> None:
    model = FakeCrossEncoder()

    assert CrossEncoderReranker(model=model).rerank("q", [chunk("a", 1)], top_k=0) == []


def test_a_model_failure_becomes_a_reranker_error() -> None:
    reranker = CrossEncoderReranker(model=FakeCrossEncoder(fail=True))

    with pytest.raises(RerankerError, match="Reranking failed"):
        reranker.rerank("q", [chunk("a", 1)], top_k=1)


def test_a_mismatched_score_count_is_rejected() -> None:
    reranker = CrossEncoderReranker(model=WrongLengthEncoder())

    with pytest.raises(RerankerError, match="Expected 2 scores"):
        reranker.rerank("q", [chunk("a", 1), chunk("b", 2)], top_k=2)


def test_metadata_survives_reranking() -> None:
    model = FakeCrossEncoder({"a": 1.0})
    original = chunk("a", 1)

    result = CrossEncoderReranker(model=model).rerank("q", [original], top_k=1)[0]

    assert result.chunk_id == original.chunk_id
    assert result.filename == original.filename
