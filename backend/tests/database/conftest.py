"""Fixtures for tests that run against a real PostgreSQL database.

These tests are skipped when no database is reachable, so the unit suite still
runs without Docker. Start one with `make up`.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://examrag:examrag@localhost:5432/examrag"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session inside a transaction that is always rolled back.

    Tests therefore share the development database without leaving rows behind.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_async_engine(url, poolclass=None)
    try:
        connection = await engine.connect()
    except (SQLAlchemyError, OSError) as exc:
        await engine.dispose()
        pytest.skip(f"No database available at {url}: {exc}")

    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        # A test that provoked an IntegrityError has already ended the
        # transaction, so only roll back one that is still open.
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()
