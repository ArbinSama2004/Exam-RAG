"""Run an uploaded document through to stored, retrievable chunks.

The pipeline coordinates the stages; it implements none of them. Each stage is
recorded on the ingestion job as it starts, so the frontend can poll for
progress and a failure says which stage failed rather than only that something
did.

```text
LOADING → CONVERTING → CLEANING → CHUNKING → EMBEDDING → INDEXING → COMPLETED
```
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session_factory
from examrag.database.models import Document, IngestionJob
from examrag.database.vector_store import replace_chunks
from examrag.embeddings.embedding_generator import EmbeddingGenerator, get_shared_generator
from examrag.enums import IngestionStage, ProcessingStatus
from examrag.ingestion.chunker import CHUNKER_VERSION, chunk_document
from examrag.ingestion.document_loader import load_document
from examrag.ingestion.file_storage import content_hash, read_upload
from examrag.ingestion.markdown_cleaner import clean_document

logger = logging.getLogger(__name__)


async def process_document(
    document_id: uuid.UUID, generator: EmbeddingGenerator | None = None
) -> None:
    """Ingest a document in its own session and transaction.

    This is what the upload endpoint schedules as a background task, so it
    cannot borrow the request's session — that is closed once the response is
    sent.
    """
    async with get_session_factory()() as session:
        document = await session.get(Document, document_id)
        if document is None:
            logger.error("Ingestion asked for unknown document %s", document_id)
            return
        await run_ingestion(session, document, generator or get_shared_generator())
        await session.commit()


async def run_ingestion(
    session: AsyncSession,
    document: Document,
    generator: EmbeddingGenerator,
) -> None:
    """Load, clean, chunk, embed and store one document.

    Failures are recorded on the document and its job rather than raised: a
    background task has nobody to raise to, and a `FAILED` status with a message
    is what the frontend polls for.
    """
    job = await _current_job(session, document)
    await _advance(session, document, job, ProcessingStatus.PROCESSING, IngestionStage.LOADING)

    try:
        data = read_upload(document.stored_path)
        loaded = load_document(document.filename, data)

        await _advance(session, document, job, stage=IngestionStage.CLEANING)
        cleaned = clean_document(loaded)
        document.normalized_content_hash = _normalized_hash(cleaned.markdown)

        await _advance(session, document, job, stage=IngestionStage.CHUNKING)
        chunks = chunk_document(cleaned)

        await _advance(session, document, job, stage=IngestionStage.EMBEDDING)
        embeddings = generator.embed_texts([chunk.content for chunk in chunks])

        await _advance(session, document, job, stage=IngestionStage.INDEXING)
        await replace_chunks(
            session,
            document,
            chunks,
            embeddings,
            embedding_model=generator.model_name,
            chunker_version=CHUNKER_VERSION,
        )
    except Exception as exc:
        logger.exception("Ingestion failed for document %s", document.id)
        await _fail(session, document, job, exc)
        return

    await _advance(
        session,
        document,
        job,
        ProcessingStatus.READY,
        IngestionStage.COMPLETED,
    )
    job.finished_at = datetime.now(UTC)
    await session.flush()
    logger.info("Document %s is ready with %d chunk(s)", document.id, document.chunk_count)


async def _current_job(session: AsyncSession, document: Document) -> IngestionJob:
    """Return the document's most recent job, creating one if it has none."""
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        job = IngestionJob(document_id=document.id)
        session.add(job)
        await session.flush()
    return job


async def _advance(
    session: AsyncSession,
    document: Document,
    job: IngestionJob,
    status: ProcessingStatus | None = None,
    stage: IngestionStage | None = None,
) -> None:
    """Record progress and commit it, so a poller sees the stage as it happens."""
    if status is not None:
        document.status = status
        job.status = status
        if status is ProcessingStatus.PROCESSING and job.started_at is None:
            job.started_at = datetime.now(UTC)
    if stage is not None:
        job.stage = stage
    await session.commit()


async def _fail(
    session: AsyncSession, document: Document, job: IngestionJob, exc: Exception
) -> None:
    # Anything partially written belongs to a run that did not finish.
    await session.rollback()
    document = await session.merge(document)
    job = await session.merge(job)

    document.status = ProcessingStatus.FAILED
    job.status = ProcessingStatus.FAILED
    job.error_message = f"{type(exc).__name__}: {exc}"[:1000]
    job.finished_at = datetime.now(UTC)
    await session.commit()


async def recover_interrupted_jobs(session: AsyncSession) -> int:
    """Fail any job a previous process left mid-run.

    A background task cannot survive the process exiting: if a job is still
    `UPLOADED` or `PROCESSING`, nothing is actually working on it. Left alone
    it stays stuck forever — the frontend polls a status that never changes,
    and re-uploading the same file finds a document that is not `FAILED`, so
    the retry-in-place logic in `api/upload.py` never fires for it either.
    Marking it `FAILED` here is what makes that retry path reachable again.

    Meant to run once, after migrations and before the API starts serving
    traffic — see `scripts/recover_interrupted_jobs.py` and the `backend`
    service command in docker-compose.yml — not as part of a request.

    Returns:
        The number of jobs recovered.
    """
    result = await session.execute(
        select(IngestionJob).where(
            IngestionJob.status.in_((ProcessingStatus.UPLOADED, ProcessingStatus.PROCESSING))
        )
    )
    jobs = list(result.scalars())
    if not jobs:
        return 0

    now = datetime.now(UTC)
    for job in jobs:
        job.status = ProcessingStatus.FAILED
        job.error_message = "Ingestion was interrupted by a server restart."
        job.finished_at = now

        document = await session.get(Document, job.document_id)
        if document is not None:
            document.status = ProcessingStatus.FAILED

    await session.flush()
    logger.warning("Recovered %d interrupted ingestion job(s) on startup", len(jobs))
    return len(jobs)


def _normalized_hash(markdown: str) -> str:
    """Hash of the cleaned Markdown.

    Two different source files can normalize to identical content, so this is
    what says whether re-embedding would produce anything new.
    """
    return content_hash(markdown.encode("utf-8"))
