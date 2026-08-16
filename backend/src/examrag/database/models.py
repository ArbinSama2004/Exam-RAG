"""ORM models for documents, ingestion jobs and chunks.

The schema carries everything ingestion and retrieval need: document purpose,
the hashes used for duplicate protection, the embedding model and chunker
version that produced each row, and — on chunks — both the pgvector embedding
and the PostgreSQL full-text vector used by hybrid retrieval.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from examrag.database.connection import Base
from examrag.enums import (
    DocumentPurpose,
    DocumentType,
    IngestionStage,
    ProcessingStatus,
)

#: Dimensionality of the embedding vectors stored in `chunks.embedding`.
#: Matches sentence-transformers/all-MiniLM-L6-v2. Changing it requires a
#: migration and re-embedding every chunk, which is why the value is a module
#: constant rather than a setting.
EMBEDDING_DIMENSIONS = 384

#: Text search configuration used for the keyword half of hybrid retrieval.
TEXT_SEARCH_CONFIG = "english"


def _enum(python_enum: type, name: str) -> Enum:
    """Build a native PostgreSQL enum that stores the member values."""
    return Enum(
        python_enum,
        name=name,
        native_enum=True,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


class TimestampMixin:
    """Creation and update timestamps maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Document(TimestampMixin, Base):
    """An uploaded file and the state of its normalization into chunks."""

    __tablename__ = "documents"
    __table_args__ = (
        # The same file may be registered once per purpose, so a paper can be
        # study material and a past paper, but re-uploading an unchanged file
        # for the same purpose is rejected instead of re-embedded.
        UniqueConstraint("original_file_hash", "purpose", name="uq_documents_hash_purpose"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_purpose", "purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        _enum(DocumentType, "document_type"),
        nullable=False,
    )
    purpose: Mapped[DocumentPurpose] = mapped_column(
        _enum(DocumentPurpose, "document_purpose"),
        nullable=False,
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        _enum(ProcessingStatus, "processing_status"),
        nullable=False,
        default=ProcessingStatus.UPLOADED,
    )

    #: Path of the stored upload, relative to the configured upload directory.
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: SHA-256 of the uploaded bytes; identifies a byte-identical re-upload.
    original_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: SHA-256 of the normalized Markdown; set once conversion has run. Two
    #: different source files can normalize to the same content.
    normalized_content_hash: Mapped[str | None] = mapped_column(String(64))

    #: Provenance of the stored chunks and vectors, so stale rows are
    #: detectable when either the model or the chunking strategy changes.
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    chunker_version: Mapped[str | None] = mapped_column(String(64))

    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class IngestionJob(TimestampMixin, Base):
    """One processing attempt for a document.

    Job state lives in PostgreSQL rather than in memory so the frontend can
    poll it and so a crashed run is visible afterwards.
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ingestion_jobs_document_id", "document_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        _enum(ProcessingStatus, "processing_status"),
        nullable=False,
        default=ProcessingStatus.UPLOADED,
    )
    stage: Mapped[IngestionStage] = mapped_column(
        _enum(IngestionStage, "ingestion_stage"),
        nullable=False,
        default=IngestionStage.QUEUED,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="ingestion_jobs")


class Chunk(TimestampMixin, Base):
    """A retrievable slice of normalized Markdown, with its embedding.

    The embedding is a column on the chunk rather than a separate table: the
    application stores exactly one vector per chunk, and keeping them together
    lets hybrid retrieval filter, rank and read metadata without a join.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_document_id", "document_id"),
        Index(
            "ix_chunks_content_tsv",
            "content_tsv",
            postgresql_using="gin",
        ),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Position within the document, starting at 0.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: Retrieval metadata, so an answer can be traced back to its source.
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(512))
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    #: Maintained by PostgreSQL, so keyword search can never drift from the
    #: chunk text it indexes.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{TEXT_SEARCH_CONFIG}', content)", persisted=True),
        nullable=False,
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
