"""Tests that exercise the migrated schema against a real PostgreSQL database."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk, Document, IngestionJob
from examrag.enums import DocumentPurpose, DocumentType, IngestionStage, ProcessingStatus


def make_document(**overrides: object) -> Document:
    defaults: dict[str, object] = {
        "filename": "networking.pdf",
        "document_type": DocumentType.PDF,
        "purpose": DocumentPurpose.STUDY_MATERIAL,
        "stored_path": f"{uuid.uuid4()}.pdf",
        "size_bytes": 2048,
        "original_file_hash": uuid.uuid4().hex,
    }
    defaults.update(overrides)
    return Document(**defaults)


async def test_pgvector_extension_is_installed(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert result.scalar_one() == "vector"


async def test_document_defaults_are_applied_on_insert(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()
    await db_session.refresh(document)

    assert document.id is not None
    assert document.status is ProcessingStatus.UPLOADED
    assert document.chunk_count == 0
    assert document.created_at is not None
    # Not yet normalized, so these stay empty until ingestion fills them in.
    assert document.normalized_content_hash is None
    assert document.embedding_model is None
    assert document.chunker_version is None


async def test_reuploading_an_unchanged_file_is_rejected(db_session: AsyncSession) -> None:
    file_hash = uuid.uuid4().hex
    db_session.add(make_document(original_file_hash=file_hash))
    await db_session.flush()

    db_session.add(make_document(original_file_hash=file_hash))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_the_same_file_may_be_registered_under_each_purpose(
    db_session: AsyncSession,
) -> None:
    file_hash = uuid.uuid4().hex
    db_session.add(make_document(original_file_hash=file_hash))
    db_session.add(make_document(original_file_hash=file_hash, purpose=DocumentPurpose.PAST_PAPER))

    await db_session.flush()  # no IntegrityError


async def test_chunk_index_is_unique_within_a_document(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    db_session.add(Chunk(document=document, chunk_index=0, content="TCP", char_count=3))
    await db_session.flush()

    db_session.add(Chunk(document=document, chunk_index=0, content="UDP", char_count=3))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_content_tsv_is_generated_and_searchable(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    chunk = Chunk(
        document=document,
        chunk_index=0,
        content="TCP provides reliable, connection-oriented transport.",
        char_count=52,
        page_number=7,
        heading="Transport Layer",
    )
    db_session.add(chunk)
    await db_session.flush()

    # The column is maintained by PostgreSQL, so keyword search never drifts
    # from the chunk text.
    match = await db_session.execute(
        select(Chunk.id).where(
            Chunk.id == chunk.id,
            Chunk.content_tsv.op("@@")(func.plainto_tsquery("english", "reliable transport")),
        )
    )
    assert match.scalar_one() == chunk.id

    no_match = await db_session.execute(
        select(Chunk.id).where(
            Chunk.id == chunk.id,
            Chunk.content_tsv.op("@@")(func.plainto_tsquery("english", "photosynthesis")),
        )
    )
    assert no_match.scalar_one_or_none() is None


async def test_embeddings_round_trip_and_rank_by_cosine_distance(
    db_session: AsyncSession,
) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    near = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
    far = [0.0] * (EMBEDDING_DIMENSIONS - 1) + [1.0]
    db_session.add(
        Chunk(document=document, chunk_index=0, content="near", char_count=4, embedding=near)
    )
    db_session.add(
        Chunk(document=document, chunk_index=1, content="far", char_count=3, embedding=far)
    )
    await db_session.flush()

    ranked = await db_session.execute(
        select(Chunk.content)
        .where(Chunk.document_id == document.id)
        .order_by(Chunk.embedding.cosine_distance(near))
    )
    assert list(ranked.scalars()) == ["near", "far"]


async def test_deleting_a_document_removes_its_chunks_and_jobs(
    db_session: AsyncSession,
) -> None:
    document = make_document()
    document.chunks.append(Chunk(chunk_index=0, content="OSI model", char_count=9))
    document.ingestion_jobs.append(
        IngestionJob(status=ProcessingStatus.READY, stage=IngestionStage.COMPLETED)
    )
    db_session.add(document)
    await db_session.flush()
    document_id = document.id

    await db_session.delete(document)
    await db_session.flush()

    remaining_chunks = await db_session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    remaining_jobs = await db_session.execute(
        select(func.count())
        .select_from(IngestionJob)
        .where(IngestionJob.document_id == document_id)
    )
    assert remaining_chunks.scalar_one() == 0
    assert remaining_jobs.scalar_one() == 0


async def test_ingestion_job_tracks_status_and_stage(db_session: AsyncSession) -> None:
    document = make_document()
    db_session.add(document)
    await db_session.flush()

    job = IngestionJob(document_id=document.id)
    db_session.add(job)
    await db_session.flush()
    await db_session.refresh(job)

    assert job.status is ProcessingStatus.UPLOADED
    assert job.stage is IngestionStage.QUEUED
    assert job.error_message is None
    assert job.finished_at is None

    job.status = ProcessingStatus.FAILED
    job.stage = IngestionStage.EMBEDDING
    job.error_message = "model download failed"
    await db_session.flush()
    await db_session.refresh(job)

    assert job.status is ProcessingStatus.FAILED
    assert job.error_message == "model download failed"


async def test_invalid_status_values_are_rejected_by_the_database(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(Exception):  # noqa: B017 - asyncpg raises its own DataError
        await db_session.execute(text("SELECT 'ARCHIVED'::processing_status"))
