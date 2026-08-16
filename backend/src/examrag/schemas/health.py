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
    """Readiness response: the API and its required dependencies are usable."""

    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]
