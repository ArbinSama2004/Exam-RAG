"""Model-level tests that do not need a database connection."""

from examrag.database.connection import Base
from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk, Document, IngestionJob
from examrag.enums import DocumentPurpose, DocumentType, IngestionStage, ProcessingStatus


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {"documents", "ingestion_jobs", "chunks"}


def test_document_purpose_matches_the_specification() -> None:
    assert [purpose.value for purpose in DocumentPurpose] == ["STUDY_MATERIAL", "PAST_PAPER"]


def test_processing_status_matches_the_specification() -> None:
    assert [status.value for status in ProcessingStatus] == [
        "UPLOADED",
        "PROCESSING",
        "READY",
        "FAILED",
    ]


def test_supported_document_types() -> None:
    assert {doc_type.value for doc_type in DocumentType} == {"PDF", "DOCX", "MARKDOWN", "TXT"}


def test_ingestion_stage_starts_queued_and_ends_completed() -> None:
    stages = list(IngestionStage)
    assert stages[0] is IngestionStage.QUEUED
    assert stages[-1] is IngestionStage.COMPLETED


def test_duplicate_protection_columns_exist() -> None:
    """Every field the spec requires for duplicate detection is stored."""
    columns = Document.__table__.columns
    for name in (
        "original_file_hash",
        "normalized_content_hash",
        "embedding_model",
        "chunker_version",
        "status",
    ):
        assert name in columns

    # The original hash is known at upload time; the rest are filled in later.
    assert columns["original_file_hash"].nullable is False
    assert columns["normalized_content_hash"].nullable is True
    assert columns["embedding_model"].nullable is True
    assert columns["chunker_version"].nullable is True


def test_a_file_is_unique_per_purpose() -> None:
    constraint = next(
        c for c in Document.__table__.constraints if c.name == "uq_documents_hash_purpose"
    )
    assert {column.name for column in constraint.columns} == {"original_file_hash", "purpose"}


def test_chunk_index_is_unique_within_a_document() -> None:
    constraint = next(
        c for c in Chunk.__table__.constraints if c.name == "uq_chunks_document_index"
    )
    assert {column.name for column in constraint.columns} == {"document_id", "chunk_index"}


def test_chunk_embedding_uses_the_declared_dimensions() -> None:
    assert EMBEDDING_DIMENSIONS == 384
    assert Chunk.__table__.columns["embedding"].type.dim == EMBEDDING_DIMENSIONS


def test_chunk_carries_source_metadata_for_traceability() -> None:
    columns = Chunk.__table__.columns
    for name in ("document_id", "chunk_index", "page_number", "heading", "content"):
        assert name in columns


def test_chunk_has_both_retrieval_indexes() -> None:
    indexes = {index.name for index in Chunk.__table__.indexes}
    assert "ix_chunks_content_tsv" in indexes
    assert "ix_chunks_embedding_hnsw" in indexes


def test_chunks_and_jobs_cascade_from_their_document() -> None:
    for table in (Chunk.__table__, IngestionJob.__table__):
        foreign_key = next(iter(table.c.document_id.foreign_keys))
        assert foreign_key.ondelete == "CASCADE"
