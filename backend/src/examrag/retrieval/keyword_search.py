"""Keyword search through PostgreSQL full-text search.

Complements vector search on the cases embeddings handle worst: exact terms,
acronyms, protocol names and numbers, where the user wants the chunk that
literally says `TCP` rather than one that is merely about transport.

The `chunks.content_tsv` column is maintained by PostgreSQL and indexed with
GIN, so nothing is computed here at query time.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import TEXT_SEARCH_CONFIG, Chunk, Document
from examrag.retrieval.base import (
    RetrievalQuery,
    RetrievedChunk,
    Retriever,
    rank_results,
)
from examrag.retrieval.filters import chunk_filters

logger = logging.getLogger(__name__)


class KeywordRetriever(Retriever):
    """Ranks chunks by PostgreSQL text-search relevance."""

    name = "keyword"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(self, query: RetrievalQuery, top_k: int) -> list[RetrievedChunk]:
        if not query.text.strip() or top_k <= 0:
            return []

        # websearch_to_tsquery accepts what a user would actually type —
        # quoted phrases, `or`, `-` for exclusion — and never raises on
        # malformed input, unlike to_tsquery.
        tsquery = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query.text)

        # ts_rank_cd accounts for how close the matched terms are to each
        # other, which suits chunk-sized passages better than plain ts_rank.
        rank = func.ts_rank_cd(Chunk.content_tsv, tsquery).label("rank")

        statement = (
            select(Chunk, Document.filename, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(chunk_filters(query), Chunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(top_k)
        )

        rows = (await self._session.execute(statement)).all()
        logger.debug("Keyword search returned %d chunk(s) for %r", len(rows), query.text)

        return rank_results(
            [
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    score=float(rank_value),
                    rank=0,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                )
                for chunk, filename, rank_value in rows
            ]
        )
