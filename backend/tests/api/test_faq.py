"""Tests for POST /faq/generate against a real database."""

import hashlib
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.database.models import Chunk, Document
from examrag.dependencies import get_embedding_generator
from examrag.embeddings.embedding_generator import EMBEDDING_DIMENSIONS, EmbeddingGenerator
from examrag.enums import DocumentPurpose, ProcessingStatus
from examrag.main import create_app

from ..database.test_schema_integration import make_document

QUESTION = "1. Explain the OSI model in detail. [10 marks]"


class HashEncoder:
    """Deterministic stand-in for the real model: identical text, identical vector."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        show_progress_bar: bool = False,
    ) -> list[list[float]]:
        vectors = []
        for text in sentences:
            vector = [0.0] * self.dimensions
            index = int(hashlib.sha256(text.encode()).hexdigest(), 16) % self.dimensions
            vector[index] = 1.0
            vectors.append(vector)
        return vectors

    def get_embedding_dimension(self) -> int | None:
        return self.dimensions


class FailingEncoder(HashEncoder):
    """Simulates the embedding model being unavailable."""

    def encode(self, *args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("model unavailable")


def build_app(db_session: AsyncSession, generator: EmbeddingGenerator) -> FastAPI:
    app: FastAPI = create_app()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_embedding_generator] = lambda: generator
    return app


@pytest.fixture
async def api(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = build_app(db_session, EmbeddingGenerator(encoder=HashEncoder()))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def past_paper(**overrides: object) -> Document:
    overrides.setdefault("purpose", DocumentPurpose.PAST_PAPER)
    overrides.setdefault("status", ProcessingStatus.READY)
    return make_document(**overrides)


def chunk(content: str) -> Chunk:
    return Chunk(chunk_index=0, content=content, char_count=len(content), page_number=1)


async def test_repeated_questions_are_returned_as_a_cluster(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    paper_2023 = past_paper(filename="2023.pdf")
    paper_2024 = past_paper(filename="2024.pdf")
    paper_2023.chunks = [chunk(QUESTION)]
    paper_2024.chunks = [chunk(QUESTION)]
    db_session.add_all([paper_2023, paper_2024])
    await db_session.flush()

    response = await api.post("/faq/generate", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["question_count"] == 2
    assert body["document_count"] == 2
    assert len(body["clusters"]) == 1
    cluster = body["clusters"][0]
    assert cluster["occurrence_count"] == 2
    assert cluster["representative"] == "Explain the OSI model in detail."
    assert {source["filename"] for source in cluster["sources"]} == {"2023.pdf", "2024.pdf"}


async def test_singleton_questions_are_hidden_by_default(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    paper = past_paper()
    paper.chunks = [chunk(QUESTION)]
    db_session.add(paper)
    await db_session.flush()

    response = await api.post("/faq/generate", json={})

    assert response.json()["clusters"] == []


async def test_min_occurrences_can_be_relaxed(api: AsyncClient, db_session: AsyncSession) -> None:
    paper = past_paper()
    paper.chunks = [chunk(QUESTION)]
    db_session.add(paper)
    await db_session.flush()

    response = await api.post("/faq/generate", json={"min_occurrences": 1})

    assert len(response.json()["clusters"]) == 1


async def test_can_scope_to_specific_document_ids(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    included = past_paper(filename="included.pdf")
    excluded = past_paper(filename="excluded.pdf")
    included.chunks = [chunk(QUESTION)]
    excluded.chunks = [chunk(QUESTION)]
    db_session.add_all([included, excluded])
    await db_session.flush()

    response = await api.post(
        "/faq/generate",
        json={"document_ids": [str(included.id)], "min_occurrences": 1},
    )

    body = response.json()
    assert body["question_count"] == 1
    assert body["clusters"][0]["sources"][0]["filename"] == "included.pdf"


async def test_no_past_papers_returns_an_empty_response(api: AsyncClient) -> None:
    response = await api.post("/faq/generate", json={})

    assert response.status_code == 200
    assert response.json() == {"question_count": 0, "document_count": 0, "clusters": []}


async def test_an_embedding_failure_returns_503_not_500(db_session: AsyncSession) -> None:
    """A missing embedding model must not surface as an unhandled 500."""
    paper = past_paper()
    paper.chunks = [chunk(QUESTION)]
    db_session.add(paper)
    await db_session.flush()

    app = build_app(db_session, EmbeddingGenerator(encoder=FailingEncoder()))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/faq/generate", json={})

    assert response.status_code == 503
