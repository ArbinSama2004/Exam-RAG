"""Domain enumerations shared by the ORM models, schemas and API layer."""

from enum import StrEnum


class DocumentPurpose(StrEnum):
    """How an uploaded document may be used.

    Past papers feed question extraction and FAQ analysis only; they are never
    used as answer evidence.
    """

    STUDY_MATERIAL = "STUDY_MATERIAL"
    PAST_PAPER = "PAST_PAPER"


class DocumentType(StrEnum):
    """Supported source formats. PDF and DOCX are normalized to Markdown."""

    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    TXT = "TXT"


class ProcessingStatus(StrEnum):
    """Canonical ingestion status, shared by documents and ingestion jobs."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class IngestionStage(StrEnum):
    """Finer-grained progress reported to the frontend while PROCESSING."""

    QUEUED = "QUEUED"
    LOADING = "LOADING"
    CONVERTING = "CONVERTING"
    CLEANING = "CLEANING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
