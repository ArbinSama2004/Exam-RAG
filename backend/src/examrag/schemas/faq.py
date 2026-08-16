"""Request and response schemas for the past-paper FAQ generator."""

import uuid

from pydantic import BaseModel, Field


class FaqGenerateRequest(BaseModel):
    """What to generate FAQs from."""

    #: Past papers to scope to, or every ready past paper when empty.
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    #: A cluster below this many members is not a "frequently asked" question.
    min_occurrences: int = Field(default=2, ge=1, le=50)


class FaqSourceResponse(BaseModel):
    """Where one occurrence of a clustered question came from."""

    document_id: uuid.UUID
    filename: str
    page_number: int | None = None
    heading: str | None = None


class FaqClusterResponse(BaseModel):
    """A question, in its clearest phrasing, and how often it recurs."""

    representative: str
    occurrence_count: int
    document_count: int
    variants: list[str]
    sources: list[FaqSourceResponse]


class FaqGenerateResponse(BaseModel):
    """Every cluster that met `min_occurrences`, plus the totals behind them."""

    question_count: int
    document_count: int
    clusters: list[FaqClusterResponse]
