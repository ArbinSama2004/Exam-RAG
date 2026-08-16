"""Request and response schemas for document upload and status."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from examrag.enums import DocumentPurpose, DocumentType, IngestionStage, ProcessingStatus


class DocumentSummary(BaseModel):
    """A document as the frontend lists it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    document_type: DocumentType
    purpose: DocumentPurpose
    status: ProcessingStatus
    size_bytes: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    """A document with the provenance of its stored chunks."""

    embedding_model: str | None = None
    chunker_version: str | None = None
    original_file_hash: str
    normalized_content_hash: str | None = None


class IngestionStatus(BaseModel):
    """What the frontend polls while a document is being processed."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    job_id: uuid.UUID
    status: ProcessingStatus
    stage: IngestionStage
    chunk_count: int
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class UploadResponse(BaseModel):
    """The result of an upload."""

    document: DocumentSummary
    job_id: uuid.UUID
    reused: bool = Field(
        default=False,
        description=(
            "True when this file had already been uploaded for this purpose and "
            "the existing document was returned instead of being processed again."
        ),
    )
