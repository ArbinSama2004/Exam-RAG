"""Health and readiness endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.config import Settings, get_settings
from examrag.database.connection import get_session
from examrag.generation.llm_client import check_llm_available
from examrag.schemas.health import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Report that the API process is running. Does not touch dependencies."""
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReadinessResponse:
    """Report whether the database is reachable."""
    llm_ok, llm_detail = await check_llm_available()

    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Readiness check failed: database is unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            database="unavailable",
            llm="ok" if llm_ok else "unavailable",
            llm_detail=llm_detail,
        )

    return ReadinessResponse(
        status="ready",
        database="ok",
        llm="ok" if llm_ok else "unavailable",
        llm_detail=llm_detail,
    )
