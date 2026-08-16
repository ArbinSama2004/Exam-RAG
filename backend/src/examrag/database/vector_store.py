"""Persist and read chunks with their embeddings.

This is the only module that writes to `chunks`. Keeping the writes here means
the rules that make a document retrievable — chunks replaced as a set, counts
and provenance recorded together — live in one place instead of being repeated
by every caller.

Retrieval reads (vector, keyword, hybrid) belong to the `retrieval` package and
are added in Phase 2.
"""

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import Chunk, Document
from examrag.ingestion.chunker import TextChunk

logger = logging.getLogger(__name__)


async def replace_chunks(
    session: AsyncSession,
    document: Document,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    *,
    embedding_model: str,
    chunker_version: str,
) -> int:
    """Store a document's chunks, replacing any it already had.

    Replacing rather than appending means re-ingesting a document is safe: a
    failed or superseded run cannot leave orphaned chunks that retrieval would
    still return.

    Args:
        session: Session to write through. The caller owns the transaction.
        document: The document being ingested.
        chunks: Chunks in reading order.
        embeddings: One vector per chunk, in the same order.
        embedding_model: Model that produced the vectors.
        chunker_version: Chunker that produced the chunks.

    Returns:
        The number of chunks stored.

    Raises:
        ValueError: chunks and embeddings do not line up.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Got {len(chunks)} chunks and {len(embeddings)} embeddings; they must match."
        )

    await delete_chunks(session, document.id)

    session.add_all(
        [
            Chunk(
                document_id=document.id,
                chunk_index=chunk.index,
                content=chunk.content,
                page_number=chunk.page_number,
                heading=chunk.heading,
                char_count=chunk.char_count,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
    )

    # Recorded together with the chunks so a document always says which model
    # and chunker its stored vectors came from.
    document.chunk_count = len(chunks)
    document.embedding_model = embedding_model
    document.chunker_version = chunker_version

    await session.flush()
    logger.info("Stored %d chunk(s) for document %s", len(chunks), document.id)
    return len(chunks)


async def delete_chunks(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Remove every chunk belonging to a document.

    Returns:
        The number of chunks removed.
    """
    removed = await count_chunks(session, document_id)
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    return removed


async def count_chunks(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Count the chunks stored for a document."""
    result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    return int(result.scalar_one())


async def count_embedded_chunks(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Count chunks that actually carry a vector.

    A chunk without one is invisible to vector search, so this is the check
    that a document is genuinely retrievable.
    """
    result = await session.execute(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.document_id == document_id, Chunk.embedding.isnot(None))
    )
    return int(result.scalar_one())


async def get_chunks(session: AsyncSession, document_id: uuid.UUID) -> list[Chunk]:
    """Return a document's chunks in reading order."""
    result = await session.execute(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
    )
    return list(result.scalars())
