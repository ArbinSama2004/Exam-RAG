"""Schemas for retrieval comparison and grounded answers."""

import uuid

from pydantic import BaseModel, Field

from examrag.enums import DocumentPurpose


class RetrievalRequest(BaseModel):
    """A query to run against the uploaded material."""

    query: str = Field(min_length=1, max_length=1000)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    purpose: DocumentPurpose = DocumentPurpose.STUDY_MATERIAL


class RetrievedChunkResponse(BaseModel):
    """One retrieved chunk with the metadata needed to inspect it."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    content: str
    score: float
    rank: int
    page_number: int | None = None
    heading: str | None = None
    source: str


class RetrievalComparison(BaseModel):
    """The same query as each retrieval method sees it.

    Every list comes from the pipeline the application actually uses, not a
    parallel implementation built for this screen.
    """

    query: str
    vector: list[RetrievedChunkResponse]
    keyword: list[RetrievedChunkResponse]
    hybrid: list[RetrievedChunkResponse]
    hybrid_reranked: list[RetrievedChunkResponse]


class AnswerPassage(BaseModel):
    """A passage the answer was generated from."""

    number: int
    text: str
    source: str
    chunk_id: str
    document_id: str


class AnswerResponse(BaseModel):
    """A grounded answer and the evidence behind it."""

    question: str
    answer: str
    passages: list[AnswerPassage]
    model: str
    is_grounded: bool
