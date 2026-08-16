"""Document upload and ingestion status endpoints.

The route handlers validate input, decide whether an upload is a duplicate and
hand processing to a background task. The ingestion work itself lives in
`ingestion/ingestion_pipeline.py`.
"""

import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.config import Settings, get_settings
from examrag.database.connection import get_session
from examrag.database.models import Document, IngestionJob
from examrag.enums import DocumentPurpose, ProcessingStatus
from examrag.ingestion.document import UnsupportedDocumentTypeError
from examrag.ingestion.document_loader import detect_document_type
from examrag.ingestion.file_storage import content_hash, save_upload
from examrag.ingestion.ingestion_pipeline import process_document
from examrag.schemas.document import (
    DocumentDetail,
    DocumentSummary,
    IngestionStatus,
    UploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="PDF, DOCX, Markdown or TXT file")],
    purpose: Annotated[DocumentPurpose, Form(description="How the document may be used")],
) -> UploadResponse:
    """Accept a document and start ingesting it in the background.

    Returns `202` with the document and its job. Poll
    `GET /documents/{id}/status` until the status is `READY` or `FAILED`.
    """
    filename = file.filename or ""
    try:
        document_type = detect_document_type(filename)
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{filename}' is empty.")

    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"'{filename}' is {len(data) / 1024 / 1024:.1f} MB, "
            f"over the {settings.max_upload_mb} MB limit.",
        )

    file_hash = content_hash(data)
    if (existing := await _find_existing(session, file_hash, purpose)) is not None:
        if existing.status is not ProcessingStatus.FAILED:
            logger.info("Reusing document %s for re-uploaded file %s", existing.id, filename)
            job = await _latest_job(session, existing)
            return UploadResponse(
                document=DocumentSummary.model_validate(existing),
                job_id=job.id,
                reused=True,
            )

        # The previous attempt produced nothing, so retry in place: a second
        # row is impossible anyway, since (file hash, purpose) is unique.
        job = await _retry(session, existing, filename, data)
        background_tasks.add_task(process_document, existing.id)
        return UploadResponse(document=DocumentSummary.model_validate(existing), job_id=job.id)

    document = Document(
        id=uuid.uuid4(),
        filename=filename,
        document_type=document_type,
        purpose=purpose,
        status=ProcessingStatus.UPLOADED,
        stored_path="",
        size_bytes=len(data),
        original_file_hash=file_hash,
    )
    document.stored_path = save_upload(document.id, filename, data)

    job = IngestionJob(document_id=document.id)
    session.add_all([document, job])
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)

    # Queued only after the commit, so the task cannot look for a row that the
    # transaction has not yet written.
    background_tasks.add_task(process_document, document.id)

    return UploadResponse(document=DocumentSummary.model_validate(document), job_id=job.id)


@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_session)],
    purpose: DocumentPurpose | None = None,
) -> list[DocumentSummary]:
    """List uploaded documents, newest first, optionally filtered by purpose."""
    query = select(Document).order_by(Document.created_at.desc())
    if purpose is not None:
        query = query.where(Document.purpose == purpose)

    result = await session.execute(query)
    return [DocumentSummary.model_validate(document) for document in result.scalars()]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetail:
    """Return one document, including which model and chunker produced its chunks."""
    return DocumentDetail.model_validate(await _require_document(session, document_id))


@router.get("/{document_id}/status", response_model=IngestionStatus)
async def get_ingestion_status(
    document_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestionStatus:
    """Return the current ingestion status. This is the polling endpoint."""
    document = await _require_document(session, document_id)
    job = await _latest_job(session, document)
    return IngestionStatus(
        document_id=document.id,
        job_id=job.id,
        status=job.status,
        stage=job.stage,
        chunk_count=document.chunk_count,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


async def _find_existing(
    session: AsyncSession, file_hash: str, purpose: DocumentPurpose
) -> Document | None:
    """Find an unchanged earlier upload of the same file for the same purpose."""
    result = await session.execute(
        select(Document).where(
            Document.original_file_hash == file_hash,
            Document.purpose == purpose,
        )
    )
    return result.scalars().first()


async def _retry(
    session: AsyncSession, document: Document, filename: str, data: bytes
) -> IngestionJob:
    """Queue a fresh attempt at a document whose last ingestion failed.

    The upload is written again, so a retry also recovers a document whose
    stored file went missing.
    """
    document.stored_path = save_upload(document.id, filename, data)
    document.status = ProcessingStatus.UPLOADED
    job = IngestionJob(document_id=document.id)
    session.add(job)
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)
    logger.info("Retrying ingestion for previously failed document %s", document.id)
    return job


async def _require_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No document with id {document_id}.")
    return document


async def _latest_job(session: AsyncSession, document: Document) -> IngestionJob:
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document {document.id} has no ingestion job."
        )
    return job
