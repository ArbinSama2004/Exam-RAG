"""Tests for storing chunks and embeddings, against a real PostgreSQL database."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk
from examrag.database.vector_store import (
    count_chunks,
    count_embedded_chunks,
    delete_chunks,
    get_chunks,
    replace_chunks,
)
from examrag.enums import DocumentPurpose, DocumentType
from examrag.ingestion.chunker import TextChunk

from .test_schema_integration import make_document

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNKER = "markdown-v1"


def vector(seed: float) -> list[float]:
    return [seed] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def sample_chunks(count: int = 3) -> list[TextChunk]:
    return [
        TextChunk(
            index=index,
            content=f"Chunk {index} content.",
            page_number=index + 1,
            heading=f"Section {index}",
        )
        for index in range(count)
    ]


async def store(session: AsyncSession, document, chunks: list[TextChunk]) -> int:
    return await replace_chunks(
        session,
        document,
        chunks,
        [vector(float(chunk.index)) for chunk in chunks],
        embedding_model=MODEL,
        chunker_version=CHUNKER,
    )


async def test_chunks_are_stored_with_their_metadata(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    stored = await store(db_session, document, sample_chunks())

    assert stored == 3
    chunks = await get_chunks(db_session, document.id)
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert chunks[1].content == "Chunk 1 content."
    assert chunks[1].page_number == 2
    assert chunks[1].heading == "Section 1"
    assert chunks[1].char_count == len("Chunk 1 content.")


async def test_embeddings_round_trip(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    await store(db_session, document, sample_chunks(2))

    chunks = await get_chunks(db_session, document.id)
    assert len(chunks[0].embedding) == EMBEDDING_DIMENSIONS
    assert chunks[1].embedding[0] == pytest.approx(1.0)


async def test_provenance_is_recorded_on_the_document(db_session: AsyncSession) -> None:
    """A document must always say which model and chunker produced its vectors."""
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    await store(db_session, document, sample_chunks())

    assert document.embedding_model == MODEL
    assert document.chunker_version == CHUNKER
    assert document.chunk_count == 3


async def test_re_ingesting_replaces_the_previous_chunks(db_session: AsyncSession) -> None:
    """Appending would leave stale chunks that retrieval would still return."""
    document = make_document()
    db_session.add(document)
    await db_session.flush()
    await store(db_session, document, sample_chunks(5))

    await store(db_session, document, sample_chunks(2))

    chunks = await get_chunks(db_session, document.id)
    assert len(chunks) == 2
    assert document.chunk_count == 2


async def test_chunks_are_returned_in_reading_order(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()
    await store(db_session, document, list(reversed(sample_chunks(4))))

    chunks = await get_chunks(db_session, document.id)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]


async def test_mismatched_chunks_and_embeddings_are_rejected(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    with pytest.raises(ValueError, match="they must match"):
        await replace_chunks(
            db_session,
            document,
            sample_chunks(3),
            [vector(0.0)],
            embedding_model=MODEL,
            chunker_version=CHUNKER,
        )


async def test_storing_no_chunks_is_allowed(db_session: AsyncSession) -> None:
    """An empty document is still a completed ingestion, not a failure."""
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    assert await store(db_session, document, []) == 0
    assert document.chunk_count == 0


async def test_every_stored_chunk_carries_a_vector(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    await store(db_session, document, sample_chunks(3))

    assert await count_chunks(db_session, document.id) == 3
    assert await count_embedded_chunks(db_session, document.id) == 3


async def test_a_chunk_without_a_vector_is_not_counted_as_embedded(
    db_session: AsyncSession,
) -> None:
    """The column is nullable, and such a chunk is invisible to vector search."""
    document = make_document()
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, content="No vector.", char_count=10)
    )
    await db_session.flush()

    assert await count_chunks(db_session, document.id) == 1
    assert await count_embedded_chunks(db_session, document.id) == 0


async def test_delete_chunks_reports_how_many_it_removed(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()
    await store(db_session, document, sample_chunks(4))

    removed = await delete_chunks(db_session, document.id)

    assert removed == 4
    assert await count_chunks(db_session, document.id) == 0


async def test_chunks_of_other_documents_are_untouched(db_session: AsyncSession) -> None:
    first = make_document()
    second = make_document(purpose=DocumentPurpose.PAST_PAPER, document_type=DocumentType.DOCX)
    db_session.add_all([first, second])
    await db_session.flush()
    await store(db_session, first, sample_chunks(2))
    await store(db_session, second, sample_chunks(3))

    await delete_chunks(db_session, first.id)

    assert await count_chunks(db_session, second.id) == 3


async def test_counting_an_unknown_document_returns_zero(db_session: AsyncSession) -> None:
    assert await count_chunks(db_session, uuid.uuid4()) == 0
