"""Tests for the retrieval comparison and answer endpoints."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.dependencies import get_llm_client, get_rag_pipeline
from examrag.rag.pipeline import RetrievalTrace
from examrag.retrieval.base import RetrievedChunk

from .test_mcq import FakeLLM


def chunk(content: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, content),
        document_id=uuid.uuid4(),
        filename="networking.pdf",
        content=content,
        score=1.0 / rank,
        rank=rank,
        page_number=rank,
        heading="Transport Layer",
    )


class TracePipeline:
    """Returns a fixed trace, so no models are loaded."""

    def __init__(self) -> None:
        self.queries: list[object] = []

    async def retrieve(self, query: object) -> RetrievalTrace:
        self.queries.append(query)
        return RetrievalTrace(
            vector=[chunk("vector hit", 1), chunk("shared", 2)],
            keyword=[chunk("keyword hit", 1)],
            fused=[chunk("shared", 1), chunk("vector hit", 2), chunk("keyword hit", 3)],
            reranked=[chunk("shared", 1)],
        )

    async def build_context(self, query: object):
        from examrag.rag.context_builder import build_context

        return build_context([chunk("shared", 1)])


@pytest.fixture
def pipeline() -> TracePipeline:
    return TracePipeline()


@pytest.fixture
async def api(db_session: AsyncSession, pipeline: TracePipeline) -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app_with(db_session, pipeline)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def create_app_with(db_session: AsyncSession, pipeline: TracePipeline) -> FastAPI:
    from examrag.main import create_app

    app = create_app()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    return app


class TestComparison:
    async def test_every_method_is_returned(self, api: AsyncClient) -> None:
        response = await api.post("/retrieval/compare", json={"query": "TCP"})

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"query", "vector", "keyword", "hybrid", "hybrid_reranked"}

    async def test_the_methods_show_different_results(self, api: AsyncClient) -> None:
        """The point of the screen: the differences must be visible."""
        body = (await api.post("/retrieval/compare", json={"query": "TCP"})).json()

        assert [item["content"] for item in body["vector"]] == ["vector hit", "shared"]
        assert [item["content"] for item in body["keyword"]] == ["keyword hit"]
        assert len(body["hybrid"]) == 3
        assert [item["content"] for item in body["hybrid_reranked"]] == ["shared"]

    async def test_results_carry_inspectable_metadata(self, api: AsyncClient) -> None:
        body = (await api.post("/retrieval/compare", json={"query": "TCP"})).json()

        first = body["vector"][0]
        assert first["rank"] == 1
        assert first["source"] == "networking.pdf, p. 1 — Transport Layer"
        assert first["filename"] == "networking.pdf"
        assert "score" in first

    async def test_the_query_reaches_the_pipeline(
        self, api: AsyncClient, pipeline: TracePipeline
    ) -> None:
        document_id = uuid.uuid4()

        await api.post(
            "/retrieval/compare",
            json={"query": "how does TCP work?", "document_ids": [str(document_id)]},
        )

        query = pipeline.queries[0]
        assert query.text == "how does TCP work?"  # type: ignore[attr-defined]
        assert query.document_ids == frozenset({document_id})  # type: ignore[attr-defined]

    async def test_an_empty_query_is_rejected(self, api: AsyncClient) -> None:
        assert (await api.post("/retrieval/compare", json={"query": ""})).status_code == 422


class TestAnswer:
    async def test_an_answer_is_returned_with_its_passages(self, api: AsyncClient) -> None:
        response = await api.post("/retrieval/answer", json={"query": "What is TCP?"})

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "An answer."
        assert body["is_grounded"] is True
        assert body["passages"][0]["source"] == "networking.pdf, p. 1 — Transport Layer"
        assert body["model"] == "fake-model"

    async def test_the_question_is_echoed_back(self, api: AsyncClient) -> None:
        body = (await api.post("/retrieval/answer", json={"query": "What is TCP?"})).json()

        assert body["question"] == "What is TCP?"
