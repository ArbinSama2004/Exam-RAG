"""Rerank fused candidates with a cross-encoder.

The bi-encoder used for vector search embeds the query and each chunk
separately, so it never sees them together. A cross-encoder reads the pair at
once and scores how well the chunk answers *this* query — much more accurate,
and far too slow to run over a whole corpus. That is why it runs last, over a
few dozen candidates rather than thousands.

An LLM is not used for reranking: it would be slower, costlier and
non-deterministic for a job a purpose-built model does better.
"""

import logging
from dataclasses import replace
from typing import Protocol, cast

from examrag.retrieval.base import RetrievedChunk

logger = logging.getLogger(__name__)

#: Cross-encoder trained on MS MARCO passage ranking. Small enough to run on
#: CPU for the candidate counts this pipeline uses.
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

#: Query/chunk pairs scored per forward pass.
RERANKER_BATCH_SIZE = 16


class RerankerError(RuntimeError):
    """The reranking model could not be loaded or failed to score."""


class CrossEncoderModel(Protocol):
    """The part of sentence-transformers' `CrossEncoder` this module uses."""

    def predict(self, sentences: list[tuple[str, str]], batch_size: int = ...) -> object: ...


class CrossEncoderReranker:
    """Reorders candidates by how well each one answers the query.

    The model loads on first use, so an application that never retrieves never
    pays for it.
    """

    name = "reranker"

    def __init__(self, model: CrossEncoderModel | None = None) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        return RERANKER_MODEL_NAME

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        """Return the `top_k` candidates most relevant to `query`, best first.

        Raises:
            RerankerError: the model is unavailable or returned the wrong shape.
        """
        if not chunks or top_k <= 0:
            return []

        model = self._load()
        pairs = [(query, chunk.content) for chunk in chunks]
        try:
            raw = model.predict(pairs, batch_size=RERANKER_BATCH_SIZE)
        except Exception as exc:
            raise RerankerError(f"Reranking failed: {exc}") from exc

        scores = [float(value) for value in cast(list[float], raw)]
        if len(scores) != len(chunks):
            raise RerankerError(f"Expected {len(chunks)} scores, got {len(scores)}.")

        ordered = sorted(zip(chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        reranked = [
            replace(chunk, score=score, rank=index)
            for index, (chunk, score) in enumerate(ordered[:top_k], start=1)
        ]

        logger.debug("Reranked %d candidate(s) down to %d", len(chunks), len(reranked))
        return reranked

    def _load(self) -> CrossEncoderModel:
        if self._model is not None:
            return self._model

        logger.info("Loading reranking model %s", RERANKER_MODEL_NAME)
        try:
            from sentence_transformers import CrossEncoder

            self._model = cast(CrossEncoderModel, CrossEncoder(RERANKER_MODEL_NAME))
        except Exception as exc:
            raise RerankerError(
                f"Could not load reranking model {RERANKER_MODEL_NAME}: {exc}"
            ) from exc
        return self._model
