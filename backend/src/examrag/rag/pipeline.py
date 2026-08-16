"""Coordinate the retrieval components into context for generation.

```text
Query
  ├─► Vector Retriever  ─┐
  └─► Keyword Retriever ─┴─► Fusion ─► Reranker ─► Context
```

This layer decides the order and the candidate counts. It implements none of
the steps — each lives in its own module in `retrieval/`, so a strategy can be
replaced, or a new one added, without touching the orchestration.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from examrag.config import Settings, get_settings
from examrag.embeddings.embedding_generator import EmbeddingGenerator
from examrag.rag.context_builder import Context, build_context
from examrag.retrieval.base import RetrievalQuery, RetrievedChunk
from examrag.retrieval.fusion import reciprocal_rank_fusion
from examrag.retrieval.keyword_search import KeywordRetriever
from examrag.retrieval.reranker import CrossEncoderReranker
from examrag.retrieval.vector_search import VectorRetriever

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    """What each stage produced, for the comparison interface and for debugging.

    Keeping the intermediate lists is what lets the Phase 2 comparison screen
    show vector-only, keyword-only, hybrid and hybrid-plus-reranking side by
    side while reusing this exact pipeline rather than a parallel one.
    """

    vector: list[RetrievedChunk]
    keyword: list[RetrievedChunk]
    fused: list[RetrievedChunk]
    reranked: list[RetrievedChunk]


class RagPipeline:
    """Runs hybrid retrieval and assembles context."""

    def __init__(
        self,
        session: AsyncSession,
        generator: EmbeddingGenerator,
        reranker: CrossEncoderReranker | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._vector = VectorRetriever(session, generator)
        self._keyword = KeywordRetriever(session)
        self._reranker = reranker or CrossEncoderReranker()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalTrace:
        """Run every stage, keeping each stage's output."""
        settings = self._settings

        vector = await self._vector.retrieve(query, settings.vector_candidates)
        keyword = await self._keyword.retrieve(query, settings.keyword_candidates)

        fused = reciprocal_rank_fusion([vector, keyword], settings.fused_candidates)

        # Reranking is the expensive stage, so it sees only the best fused
        # candidates rather than everything the two searches found.
        candidates = fused[: settings.reranker_candidates]
        reranked = (
            self._reranker.rerank(query.text, candidates, settings.final_context_chunks)
            if candidates
            else []
        )

        logger.info(
            "Retrieved %r: %d vector, %d keyword, %d fused, %d reranked",
            query.text,
            len(vector),
            len(keyword),
            len(fused),
            len(reranked),
        )
        return RetrievalTrace(vector=vector, keyword=keyword, fused=fused, reranked=reranked)

    async def build_context(self, query: RetrievalQuery) -> Context:
        """Retrieve and assemble the top-k context for generation."""
        trace = await self.retrieve(query)
        return build_context(trace.reranked)
