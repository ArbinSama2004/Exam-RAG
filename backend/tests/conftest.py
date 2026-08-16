"""Shared test fixtures."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from examrag.config import get_settings
from examrag.main import create_app

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
