"""Tests for embedding generation.

A fake encoder stands in for SentenceTransformer so the suite never downloads a
model. The real model is exercised by the opt-in test at the bottom.
"""

import os

import pytest

from examrag.database.models import EMBEDDING_DIMENSIONS
from examrag.embeddings.embedding_generator import (
    EMBEDDING_MODEL_NAME,
    EmbeddingError,
    EmbeddingGenerator,
)


class FakeEncoder:
    """Records its calls and returns vectors of the expected width."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []
        self.batch_sizes: list[int] = []
        self.normalized: list[bool] = []

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        show_progress_bar: bool = False,
    ) -> list[list[float]]:
        self.calls.append(list(sentences))
        self.batch_sizes.append(batch_size)
        self.normalized.append(normalize_embeddings)
        return [[float(index)] * self.dimensions for index, _ in enumerate(sentences)]

    def get_embedding_dimension(self) -> int | None:
        return self.dimensions


class BrokenEncoder(FakeEncoder):
    def encode(self, *args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("out of memory")


def test_embeds_every_text_in_order() -> None:
    encoder = FakeEncoder()
    generator = EmbeddingGenerator(encoder=encoder)

    vectors = generator.embed_texts(["first", "second", "third"])

    assert len(vectors) == 3
    assert encoder.calls == [["first", "second", "third"]]
    assert vectors[0][0] == 0.0
    assert vectors[2][0] == 2.0


def test_vectors_match_the_stored_dimensionality() -> None:
    vectors = EmbeddingGenerator(encoder=FakeEncoder()).embed_texts(["text"])

    assert len(vectors[0]) == EMBEDDING_DIMENSIONS


def test_embeddings_are_normalized() -> None:
    """Cosine distance in pgvector assumes unit vectors."""
    encoder = FakeEncoder()

    EmbeddingGenerator(encoder=encoder).embed_texts(["text"])

    assert encoder.normalized == [True]


def test_texts_are_batched() -> None:
    encoder = FakeEncoder()

    EmbeddingGenerator(encoder=encoder).embed_texts(["a", "b"])

    assert encoder.batch_sizes == [32]


def test_an_empty_list_needs_no_model() -> None:
    """Nothing to embed must not trigger a model load."""
    assert EmbeddingGenerator().embed_texts([]) == []


def test_embed_query_returns_a_single_vector() -> None:
    vector = EmbeddingGenerator(encoder=FakeEncoder()).embed_query("What is TCP?")

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert isinstance(vector[0], float)


def test_a_model_of_the_wrong_width_is_rejected_at_load() -> None:
    """A mismatch would otherwise surface as an opaque database insert error."""
    with pytest.raises(EmbeddingError, match="dimensional"):
        EmbeddingGenerator._validate_width(FakeEncoder(dimensions=768))


def test_output_of_the_wrong_width_is_rejected() -> None:
    generator = EmbeddingGenerator(encoder=FakeEncoder(dimensions=10))

    with pytest.raises(EmbeddingError, match="dimensional"):
        generator.embed_texts(["text"])


def test_an_encoder_failure_becomes_an_embedding_error() -> None:
    generator = EmbeddingGenerator(encoder=BrokenEncoder())

    with pytest.raises(EmbeddingError, match="Embedding failed"):
        generator.embed_texts(["text"])


def test_a_missing_model_becomes_an_embedding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(
        "examrag.embeddings.embedding_generator.EMBEDDING_MODEL_NAME",
        "examrag/definitely-not-a-real-model",
    )

    with pytest.raises(EmbeddingError, match="Could not load embedding model"):
        EmbeddingGenerator().embed_texts(["text"])


def test_model_name_is_reported_for_provenance() -> None:
    assert EmbeddingGenerator().model_name == EMBEDDING_MODEL_NAME
    assert "MiniLM" in EMBEDDING_MODEL_NAME


@pytest.mark.skipif(
    os.environ.get("EXAMRAG_TEST_REAL_MODEL") != "1",
    reason="Downloads the real model; set EXAMRAG_TEST_REAL_MODEL=1 to run.",
)
def test_the_real_model_produces_comparable_vectors() -> None:
    generator = EmbeddingGenerator()

    vectors = generator.embed_texts(
        [
            "TCP provides reliable transport.",
            "The transmission control protocol delivers data reliably.",
            "Photosynthesis converts light into chemical energy.",
        ]
    )

    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in vectors)

    def similarity(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=True))

    assert similarity(vectors[0], vectors[1]) > similarity(vectors[0], vectors[2])
