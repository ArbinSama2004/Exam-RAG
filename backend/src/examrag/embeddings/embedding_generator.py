"""Turn text into the vectors stored in pgvector.

One model serves both sides of retrieval: chunks are embedded during ingestion
and queries are embedded at search time. They must come from the same model, or
the vectors are not comparable — which is why the model name is recorded on
every document.

Vectors are L2-normalized, so cosine distance in PostgreSQL is a dot product
and the stored values are directly comparable.
"""

import logging
from functools import lru_cache
from typing import Protocol, cast

from examrag.database.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

#: The model that produces `EMBEDDING_DIMENSIONS`-wide vectors. It is a
#: constant rather than a setting for the same reason the dimensionality is:
#: it is baked into every stored vector, and changing it means a migration plus
#: re-embedding, not a restart.
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

#: Texts encoded per forward pass. Larger batches are faster but hold more
#: memory; this suits the CPU-only local deployment.
EMBEDDING_BATCH_SIZE = 32


class EmbeddingError(RuntimeError):
    """The embedding model could not be loaded or produced unusable output."""


class Encoder(Protocol):
    """The part of `SentenceTransformer` this module depends on.

    Depending on a protocol rather than the concrete class keeps tests free of
    a model download and makes the model swappable.
    """

    def encode(
        self,
        sentences: list[str],
        batch_size: int = ...,
        normalize_embeddings: bool = ...,
        show_progress_bar: bool = ...,
    ) -> object: ...

    def get_embedding_dimension(self) -> int | None: ...


class EmbeddingGenerator:
    """Generates embeddings, loading the model on first use.

    Loading costs seconds and, on a fresh install, a model download, so it is
    deferred until something actually needs a vector rather than paying it at
    application startup.
    """

    def __init__(self, encoder: Encoder | None = None) -> None:
        self._encoder = encoder

    @property
    def model_name(self) -> str:
        """Recorded on every document so stored vectors stay traceable."""
        return EMBEDDING_MODEL_NAME

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed chunk texts, preserving order.

        Raises:
            EmbeddingError: the model is unavailable or returned the wrong shape.
        """
        if not texts:
            return []

        encoder = self._load()
        try:
            raw = encoder.encode(
                texts,
                batch_size=EMBEDDING_BATCH_SIZE,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbeddingError(f"Embedding failed: {exc}") from exc

        vectors = [[float(value) for value in vector] for vector in cast(list[list[float]], raw)]
        _validate(vectors, expected_count=len(texts))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query with the same model used for chunks."""
        return self.embed_texts([text])[0]

    def _load(self) -> Encoder:
        if self._encoder is not None:
            return self._encoder

        logger.info("Loading embedding model %s", EMBEDDING_MODEL_NAME)
        try:
            from sentence_transformers import SentenceTransformer

            encoder = cast(Encoder, SentenceTransformer(EMBEDDING_MODEL_NAME))
        except Exception as exc:
            raise EmbeddingError(
                f"Could not load embedding model {EMBEDDING_MODEL_NAME}: {exc}"
            ) from exc

        self._validate_width(encoder)
        self._encoder = encoder
        return encoder

    @staticmethod
    def _validate_width(encoder: Encoder) -> None:
        """Reject a model whose vectors do not fit the database column.

        Caught here, the message names the problem; left alone, it surfaces as
        an opaque error on insert.
        """
        dimensions = encoder.get_embedding_dimension()
        if dimensions != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"{EMBEDDING_MODEL_NAME} produces {dimensions}-dimensional vectors, "
                f"but the schema stores {EMBEDDING_DIMENSIONS}."
            )


def _validate(vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingError(f"Expected {expected_count} embeddings, got {len(vectors)}.")
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings, got {len(vector)}."
            )


@lru_cache
def get_shared_generator() -> EmbeddingGenerator:
    """The process-wide generator.

    Ingestion and retrieval must use the same model anyway, and the model is
    large enough that a second copy is worth avoiding.
    """
    return EmbeddingGenerator()
