"""Response schemas for the health endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness response: the API process is running."""

    status: Literal["ok"] = "ok"
    app: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness response: the API and its dependencies.

    Only the database decides readiness. The LLM is reported so a missing model
    is visible before a user waits on a generation request, but the rest of the
    application — upload, ingestion, retrieval — works without it.
    """

    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]
    llm: Literal["ok", "unavailable"] = "unavailable"
    llm_detail: str | None = None
