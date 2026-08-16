"""Tests for the health and readiness endpoints."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from examrag.database.connection import get_session


class _FakeSession:
    """Minimal stand-in for AsyncSession used by the readiness check."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def execute(self, statement: object) -> object:
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return object()


def _override_session(app: FastAPI, *, fail: bool) -> None:
    async def _session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(fail=fail)

    app.dependency_overrides[get_session] = _session


async def test_health_reports_running_application(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "ExamRAG",
        "version": "0.1.0",
        "environment": "test",
    }


async def test_health_does_not_require_the_database(client: AsyncClient, app: FastAPI) -> None:
    _override_session(app, fail=True)

    assert (await client.get("/health")).status_code == 200


async def test_readiness_reports_ready_when_database_responds(
    client: AsyncClient, app: FastAPI
) -> None:
    _override_session(app, fail=False)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


async def test_readiness_reports_503_when_database_is_unreachable(
    client: AsyncClient, app: FastAPI
) -> None:
    _override_session(app, fail=True)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}


async def test_lifespan_creates_the_upload_directory(
    client: AsyncClient, isolated_env: Path
) -> None:
    assert (isolated_env / "uploads").is_dir()


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
def test_health_routes_are_published_in_the_openapi_schema(app: FastAPI, path: str) -> None:
    assert path in app.openapi()["paths"]
