"""Vector similarity search through pgvector.

Finds chunks whose meaning is close to the query even when they share no
words with it — the half of hybrid retrieval that handles paraphrasing.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import Chunk, Document
from examrag.embeddings.embedding_generator import EmbeddingGenerator
from examrag.retrieval.base import (
    RetrievalQuery,
    RetrievedChunk,
    Retriever,
    rank_results,
)
from examrag.retrieval.filters import chunk_filters

logger = logging.getLogger(__name__)


class VectorRetriever(Retriever):
    """Ranks chunks by cosine distance between their embedding and the query's."""

    name = "vector"

    def __init__(self, session: AsyncSession, generator: EmbeddingGenerator) -> None:
        self._session = session
        self._generator = generator

    async def retrieve(self, query: RetrievalQuery, top_k: int) -> list[RetrievedChunk]:
        if not query.text.strip() or top_k <= 0:
            return []

        # The query must be embedded by the same model as the chunks, or the
        # two vectors are not comparable.
        embedding = self._generator.embed_query(query.text)

        distance = Chunk.embedding.cosine_distance(embedding).label("distance")
        statement = (
            select(Chunk, Document.filename, distance)
            .join(Document, Chunk.document_id == Document.id)
            .where(chunk_filters(query), Chunk.embedding.isnot(None))
            .order_by(distance)
            .limit(top_k)
        )

        rows = (await self._session.execute(statement)).all()
        logger.debug("Vector search returned %d chunk(s) for %r", len(rows), query.text)

        return rank_results(
            [
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    # Embeddings are normalized, so cosine distance is in
                    # [0, 2]; 1 - distance gives the familiar similarity.
                    score=1.0 - float(distance_value),
                    rank=0,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                )
                for chunk, filename, distance_value in rows
            ]
        )
