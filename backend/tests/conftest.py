"""Shared test fixtures."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from examrag.config import get_settings
from examrag.main import create_app

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://examrag:examrag@localhost:5432/examrag"

ENV_VARS = (
    "APP_ENV",
    "DEBUG",
    "LOG_LEVEL",
    "CORS_ORIGINS",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "UPLOAD_DIR",
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate each test from the developer's environment, .env file and uploads."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def app(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Application instance configured for tests."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("UPLOAD_DIR", str(isolated_env / "uploads"))
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the application, with lifespan hooks executed."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session against a real database, inside a transaction that is rolled back.

    Skipped when no database is reachable, so the rest of the suite still runs
    without Docker. `join_transaction_mode="create_savepoint"` turns any commit
    made by the code under test into a savepoint release, so code that commits
    (the ingestion pipeline does, to publish progress) stays testable without
    leaking rows into the developer's database.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_async_engine(url, poolclass=None)
    try:
        connection = await engine.connect()
    except (SQLAlchemyError, OSError) as exc:
        await engine.dispose()
        pytest.skip(f"No database available at {url}: {exc}")

    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the upload directory at a temporary path for the duration of a test."""
    directory = tmp_path / "uploads"
    directory.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(directory))
    get_settings.cache_clear()
    yield directory
    get_settings.cache_clear()
