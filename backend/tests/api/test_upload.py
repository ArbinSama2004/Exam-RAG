"""Tests for the upload and ingestion-status endpoints.

These run against a real database. Background ingestion is replaced with a
recorder, so the endpoint contract is tested without running the pipeline —
that has its own tests.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.database.models import Document, IngestionJob
from examrag.enums import DocumentPurpose, DocumentType, IngestionStage, ProcessingStatus
from examrag.main import create_app

MARKDOWN = b"# Networking\n\nTCP provides reliable transport.\n"


@pytest.fixture
def scheduled(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Capture the documents handed to background processing."""
    captured: list[uuid.UUID] = []

    async def fake_process(document_id: uuid.UUID) -> None:
        captured.append(document_id)

    monkeypatch.setattr("examrag.api.upload.process_document", fake_process)
    return captured


@pytest.fixture
async def api(
    db_session: AsyncSession, uploads: Path, scheduled: list[uuid.UUID]
) -> AsyncIterator[AsyncClient]:
    """Client whose requests share the test's transaction, so rows roll back."""
    app: FastAPI = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def upload_payload(
    filename: str = "notes.md",
    data: bytes = MARKDOWN,
    purpose: DocumentPurpose = DocumentPurpose.STUDY_MATERIAL,
) -> dict:
    return {
        "files": {"file": (filename, data, "text/markdown")},
        "data": {"purpose": purpose.value},
    }


async def post_upload(client: AsyncClient, **kwargs) -> object:
    payload = upload_payload(**kwargs)
    return await client.post("/documents", files=payload["files"], data=payload["data"])


async def test_upload_accepts_a_document_and_schedules_ingestion(
    api: AsyncClient, scheduled: list[uuid.UUID]
) -> None:
    response = await post_upload(api)

    assert response.status_code == 202
    body = response.json()
    assert body["document"]["filename"] == "notes.md"
    assert body["document"]["purpose"] == "STUDY_MATERIAL"
    assert body["document"]["status"] == "UPLOADED"
    assert body["reused"] is False
    assert uuid.UUID(body["document"]["id"]) in scheduled


async def test_upload_stores_the_file_on_disk(api: AsyncClient, uploads: Path) -> None:
    response = await post_upload(api)

    stored = list(uploads.iterdir())
    assert len(stored) == 1
    assert stored[0].read_bytes() == MARKDOWN
    assert stored[0].stem == response.json()["document"]["id"]


async def test_purpose_is_required(api: AsyncClient) -> None:
    response = await api.post("/documents", files={"file": ("notes.md", MARKDOWN, "text/markdown")})

    assert response.status_code == 422


async def test_an_invalid_purpose_is_rejected(api: AsyncClient) -> None:
    response = await api.post(
        "/documents",
        files={"file": ("notes.md", MARKDOWN, "text/markdown")},
        data={"purpose": "LECTURE_SLIDES"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("filename", ["slides.pptx", "data.csv", "notes"])
async def test_unsupported_file_types_are_rejected(api: AsyncClient, filename: str) -> None:
    response = await post_upload(api, filename=filename)

    assert response.status_code == 400
    assert ".pdf" in response.json()["detail"]


async def test_an_empty_file_is_rejected(api: AsyncClient) -> None:
    response = await post_upload(api, data=b"")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


async def test_an_oversized_file_is_rejected(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examrag.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()

    response = await post_upload(api, data=b"x" * (2 * 1024 * 1024))

    assert response.status_code == 413
    assert "1 MB limit" in response.json()["detail"]


async def test_the_same_file_uploaded_twice_is_reused(
    api: AsyncClient, scheduled: list[uuid.UUID]
) -> None:
    """Re-uploading an unchanged file must not generate embeddings again."""
    first = await post_upload(api)

    second = await post_upload(api)

    assert second.status_code == 202
    assert second.json()["reused"] is True
    assert second.json()["document"]["id"] == first.json()["document"]["id"]
    # Only the first upload was scheduled for processing.
    assert len(scheduled) == 1


async def test_a_race_between_two_uploads_of_the_same_new_file_reuses_the_winner(
    api: AsyncClient,
    db_session: AsyncSession,
    scheduled: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two requests can both pass the duplicate check before either commits.

    The loser only finds out from the database's own unique constraint when it
    tries to insert. It must reuse the winner's row instead of surfacing an
    unhandled 500.
    """
    import examrag.api.upload as upload_module

    winner = Document(
        id=uuid.uuid4(),
        filename="notes.md",
        document_type=DocumentType.MARKDOWN,
        purpose=DocumentPurpose.STUDY_MATERIAL,
        status=ProcessingStatus.UPLOADED,
        stored_path="winner.md",
        size_bytes=len(MARKDOWN),
        original_file_hash=upload_module.content_hash(MARKDOWN),
    )
    db_session.add(winner)
    db_session.add(IngestionJob(document_id=winner.id))
    # Committed, not just flushed: this row must survive the loser's rollback
    # below, the same way it would survive as a separate, already-committed
    # request in production.
    await db_session.commit()

    real_find_existing = upload_module._find_existing
    calls = 0

    async def find_existing_once_blind(session: AsyncSession, file_hash: str, purpose: object):
        nonlocal calls
        calls += 1
        # First call: the loser's own duplicate check, before it has seen the
        # winner commit. Second call: this handler's post-conflict lookup.
        return None if calls == 1 else await real_find_existing(session, file_hash, purpose)

    monkeypatch.setattr(upload_module, "_find_existing", find_existing_once_blind)

    response = await post_upload(api)

    assert response.status_code == 202
    assert response.json()["reused"] is True
    assert response.json()["document"]["id"] == str(winner.id)
    # The loser's attempt must not have been scheduled for processing.
    assert scheduled == []


async def test_the_same_file_may_be_uploaded_under_each_purpose(
    api: AsyncClient, scheduled: list[uuid.UUID]
) -> None:
    first = await post_upload(api, purpose=DocumentPurpose.STUDY_MATERIAL)

    second = await post_upload(api, purpose=DocumentPurpose.PAST_PAPER)

    assert second.json()["reused"] is False
    assert second.json()["document"]["id"] != first.json()["document"]["id"]
    assert len(scheduled) == 2


async def test_a_failed_document_is_reprocessed_rather_than_reused(
    api: AsyncClient, db_session: AsyncSession, scheduled: list[uuid.UUID]
) -> None:
    """The earlier attempt produced nothing, so there is nothing to reuse."""
    first = await post_upload(api)
    document = await db_session.get(Document, uuid.UUID(first.json()["document"]["id"]))
    assert document is not None
    document.status = ProcessingStatus.FAILED
    await db_session.flush()

    second = await post_upload(api)

    assert second.json()["reused"] is False
    assert len(scheduled) == 2
    # Retried in place: (file hash, purpose) is unique, so a second row is
    # impossible, and the frontend keeps the document id it already knows.
    assert second.json()["document"]["id"] == first.json()["document"]["id"]
    assert second.json()["document"]["status"] == ProcessingStatus.UPLOADED.value
    assert second.json()["job_id"] != first.json()["job_id"]


async def test_a_document_orphaned_by_a_crash_is_retryable_after_recovery(
    api: AsyncClient, db_session: AsyncSession, scheduled: list[uuid.UUID]
) -> None:
    """The bug this exists to fix: before recovery, re-uploading did nothing.

    A document stuck in `PROCESSING` (the backend died mid-run) is not
    `FAILED`, so `upload_document`'s reuse branch returned it untouched on
    re-upload — the frontend would show the same stuck progress bar forever.
    Running `recover_interrupted_jobs`, exactly as the container's startup
    command does, is what makes the existing retry-in-place logic reachable.
    """
    from examrag.ingestion.ingestion_pipeline import recover_interrupted_jobs

    first = await post_upload(api)
    document = await db_session.get(Document, uuid.UUID(first.json()["document"]["id"]))
    assert document is not None
    document.status = ProcessingStatus.PROCESSING
    await db_session.flush()

    stuck_again = await post_upload(api)
    assert stuck_again.json()["reused"] is True
    assert len(scheduled) == 1  # The stuck attempt was never rescheduled.

    recovered = await recover_interrupted_jobs(db_session)
    assert recovered == 1

    retried = await post_upload(api)

    assert retried.json()["reused"] is False
    assert retried.json()["document"]["id"] == first.json()["document"]["id"]
    assert retried.json()["document"]["status"] == ProcessingStatus.UPLOADED.value
    assert len(scheduled) == 2


async def test_retrying_restores_a_missing_upload_file(
    api: AsyncClient, db_session: AsyncSession, uploads: Path
) -> None:
    """A cleared upload volume is recoverable by uploading the file again."""
    first = await post_upload(api)
    document = await db_session.get(Document, uuid.UUID(first.json()["document"]["id"]))
    assert document is not None
    document.status = ProcessingStatus.FAILED
    await db_session.flush()
    (uploads / document.stored_path).unlink()

    await post_upload(api)

    assert (uploads / document.stored_path).read_bytes() == MARKDOWN


async def test_status_reports_the_queued_job(api: AsyncClient) -> None:
    document_id = (await post_upload(api)).json()["document"]["id"]

    response = await api.get(f"/documents/{document_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["status"] == ProcessingStatus.UPLOADED.value
    assert body["stage"] == IngestionStage.QUEUED.value
    assert body["chunk_count"] == 0
    assert body["error_message"] is None


async def test_status_of_an_unknown_document_is_404(api: AsyncClient) -> None:
    response = await api.get(f"/documents/{uuid.uuid4()}/status")

    assert response.status_code == 404


async def test_documents_can_be_listed_newest_first(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    first = await post_upload(api, filename="first.md", data=b"# First\n\nContent.")
    await post_upload(api, filename="second.md", data=b"# Second\n\nContent.")

    # PostgreSQL's now() is the transaction start time, so rows written in one
    # transaction share it. Real uploads each get their own transaction.
    older = await db_session.get(Document, uuid.UUID(first.json()["document"]["id"]))
    assert older is not None
    older.created_at = older.created_at - timedelta(minutes=5)
    await db_session.flush()

    response = await api.get("/documents")

    assert response.status_code == 200
    # Filtered to this test's own uploads: the developer's database may hold
    # documents from manual testing.
    filenames = [
        document["filename"]
        for document in response.json()
        if document["filename"] in {"first.md", "second.md"}
    ]
    assert filenames == ["second.md", "first.md"]


async def test_documents_can_be_filtered_by_purpose(api: AsyncClient) -> None:
    await post_upload(api, filename="study.md", data=b"# Study\n\nContent.")
    await post_upload(
        api, filename="paper.md", data=b"# Paper\n\nContent.", purpose=DocumentPurpose.PAST_PAPER
    )

    response = await api.get("/documents", params={"purpose": DocumentPurpose.PAST_PAPER.value})

    filenames = [document["filename"] for document in response.json()]
    assert filenames == ["paper.md"]


async def test_document_detail_includes_provenance_fields(api: AsyncClient) -> None:
    document_id = (await post_upload(api)).json()["document"]["id"]

    response = await api.get(f"/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["document_type"] == DocumentType.MARKDOWN.value
    assert len(body["original_file_hash"]) == 64
    # Not yet processed, so these are still empty.
    assert body["normalized_content_hash"] is None
    assert body["embedding_model"] is None
    assert body["chunker_version"] is None


async def test_an_unknown_document_is_404(api: AsyncClient) -> None:
    response = await api.get(f"/documents/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_the_upload_endpoint_is_documented(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    paths = response.json()["paths"]
    assert "/documents" in paths
    assert "/documents/{document_id}/status" in paths
