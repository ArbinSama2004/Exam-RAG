"""Tests for the ingestion pipeline, against a real PostgreSQL database."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import EMBEDDING_DIMENSIONS, Document, IngestionJob
from examrag.database.vector_store import count_chunks, get_chunks
from examrag.embeddings.embedding_generator import EmbeddingError, EmbeddingGenerator
from examrag.enums import DocumentPurpose, DocumentType, IngestionStage, ProcessingStatus
from examrag.ingestion.chunker import CHUNKER_VERSION
from examrag.ingestion.file_storage import save_upload
from examrag.ingestion.ingestion_pipeline import recover_interrupted_jobs, run_ingestion

MARKDOWN = b"""# Networking

## Transport Layer

TCP provides reliable, connection-oriented delivery between two hosts.

## Network Layer

IP routes packets between networks without guaranteeing delivery.
"""


class StubEncoder:
    """Deterministic stand-in for the embedding model."""

    def encode(self, sentences, batch_size=32, normalize_embeddings=False, **_):
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in sentences]

    def get_embedding_dimension(self) -> int:
        return EMBEDDING_DIMENSIONS


class FailingEncoder(StubEncoder):
    def encode(self, *args, **kwargs):
        raise RuntimeError("model unavailable")


@pytest.fixture
def generator() -> EmbeddingGenerator:
    return EmbeddingGenerator(encoder=StubEncoder())


async def make_stored_document(
    session: AsyncSession, data: bytes = MARKDOWN, filename: str = "notes.md"
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        filename=filename,
        document_type=DocumentType.MARKDOWN,
        purpose=DocumentPurpose.STUDY_MATERIAL,
        status=ProcessingStatus.UPLOADED,
        stored_path="",
        size_bytes=len(data),
        original_file_hash=uuid.uuid4().hex,
    )
    document.stored_path = save_upload(document.id, filename, data)
    session.add(document)
    session.add(IngestionJob(document_id=document.id))
    await session.flush()
    return document


async def test_a_document_becomes_ready_with_chunks(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, generator)

    assert document.status is ProcessingStatus.READY
    assert document.chunk_count > 0
    assert await count_chunks(db_session, document.id) == document.chunk_count


async def test_provenance_is_recorded(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, generator)

    assert document.embedding_model == generator.model_name
    assert document.chunker_version == CHUNKER_VERSION
    assert document.normalized_content_hash is not None


async def test_chunks_keep_their_heading_metadata(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, generator)

    headings = {chunk.heading for chunk in await get_chunks(db_session, document.id)}
    assert "Networking > Transport Layer" in headings
    assert "Networking > Network Layer" in headings


async def test_every_chunk_is_embedded(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, generator)

    chunks = await get_chunks(db_session, document.id)
    assert all(len(chunk.embedding) == EMBEDDING_DIMENSIONS for chunk in chunks)


async def test_the_job_ends_completed(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, generator)
    await db_session.refresh(document, ["ingestion_jobs"])

    job = document.ingestion_jobs[0]
    assert job.status is ProcessingStatus.READY
    assert job.stage is IngestionStage.COMPLETED
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.error_message is None


async def test_a_missing_upload_fails_the_job_with_a_message(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    """A cleared volume must produce FAILED, not an unhandled background error."""
    document = await make_stored_document(db_session)
    (uploads / document.stored_path).unlink()

    await run_ingestion(db_session, document, generator)
    await db_session.refresh(document, ["ingestion_jobs"])

    assert document.status is ProcessingStatus.FAILED
    job = document.ingestion_jobs[0]
    assert job.status is ProcessingStatus.FAILED
    assert "FileNotFoundError" in (job.error_message or "")
    assert job.finished_at is not None


async def test_a_corrupt_file_fails_the_job(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(
        db_session, data=b"%PDF-1.7 not really a pdf", filename="broken.pdf"
    )
    document.document_type = DocumentType.PDF

    await run_ingestion(db_session, document, generator)

    assert document.status is ProcessingStatus.FAILED


async def test_an_embedding_failure_fails_the_job(db_session: AsyncSession, uploads: Path) -> None:
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, EmbeddingGenerator(encoder=FailingEncoder()))
    await db_session.refresh(document, ["ingestion_jobs"])

    assert document.status is ProcessingStatus.FAILED
    assert EmbeddingError.__name__ in (document.ingestion_jobs[0].error_message or "")


async def test_a_failed_document_stores_no_chunks(db_session: AsyncSession, uploads: Path) -> None:
    """A half-finished run must not leave chunks that retrieval would return."""
    document = await make_stored_document(db_session)

    await run_ingestion(db_session, document, EmbeddingGenerator(encoder=FailingEncoder()))

    assert await count_chunks(db_session, document.id) == 0


async def test_re_ingesting_replaces_the_previous_chunks(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)
    await run_ingestion(db_session, document, generator)
    first_count = document.chunk_count

    await run_ingestion(db_session, document, generator)

    assert document.chunk_count == first_count
    assert await count_chunks(db_session, document.id) == first_count


async def test_ingestion_creates_a_job_when_none_exists(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)
    for job in list(await _jobs(db_session, document)):
        await db_session.delete(job)
    await db_session.flush()

    await run_ingestion(db_session, document, generator)
    await db_session.refresh(document, ["ingestion_jobs"])

    assert len(document.ingestion_jobs) == 1


async def _jobs(session: AsyncSession, document: Document) -> list[IngestionJob]:
    await session.refresh(document, ["ingestion_jobs"])
    return list(document.ingestion_jobs)


async def test_recovery_fails_a_job_stuck_processing(
    db_session: AsyncSession, uploads: Path
) -> None:
    """A crash mid-run leaves PROCESSING behind; recovery is what unsticks it."""
    document = await make_stored_document(db_session)
    job = (await _jobs(db_session, document))[0]
    job.status = ProcessingStatus.PROCESSING
    job.stage = IngestionStage.EMBEDDING
    document.status = ProcessingStatus.PROCESSING
    await db_session.flush()

    recovered = await recover_interrupted_jobs(db_session)

    assert recovered == 1
    await db_session.refresh(document)
    await db_session.refresh(job)
    assert document.status is ProcessingStatus.FAILED
    assert job.status is ProcessingStatus.FAILED
    assert "interrupted" in (job.error_message or "").lower()
    assert job.finished_at is not None


async def test_recovery_fails_a_job_never_started(db_session: AsyncSession, uploads: Path) -> None:
    """UPLOADED with nobody working on it is exactly as orphaned as PROCESSING."""
    document = await make_stored_document(db_session)

    recovered = await recover_interrupted_jobs(db_session)

    assert recovered == 1
    await db_session.refresh(document)
    assert document.status is ProcessingStatus.FAILED


async def test_recovery_leaves_ready_documents_alone(
    db_session: AsyncSession, generator: EmbeddingGenerator, uploads: Path
) -> None:
    document = await make_stored_document(db_session)
    await run_ingestion(db_session, document, generator)

    recovered = await recover_interrupted_jobs(db_session)

    assert recovered == 0
    assert document.status is ProcessingStatus.READY


async def test_recovery_leaves_already_failed_documents_alone(
    db_session: AsyncSession, uploads: Path
) -> None:
    document = await make_stored_document(db_session)
    await run_ingestion(db_session, document, EmbeddingGenerator(encoder=FailingEncoder()))
    job = (await _jobs(db_session, document))[0]
    original_message = job.error_message

    recovered = await recover_interrupted_jobs(db_session)

    assert recovered == 0
    assert job.error_message == original_message


async def test_recovery_with_nothing_stuck_is_a_no_op(db_session: AsyncSession) -> None:
    assert await recover_interrupted_jobs(db_session) == 0
