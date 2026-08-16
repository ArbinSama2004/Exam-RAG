"""The retrieval interface every strategy implements.

Vector and keyword search both return the same shape, which is what lets fusion
combine them without knowing where a result came from — and what would let a
future graph retriever join in without touching the pipeline, the API or the
frontend.

Do not add a graph retriever now; the interface exists so that adding one later
is not a rewrite.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

from examrag.enums import DocumentPurpose


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """What to search for, and what to search over.

    `purpose` defaults to study material because past papers must never be used
    as answer evidence. Question extraction asks for `PAST_PAPER` explicitly.
    """

    text: str
    purpose: DocumentPurpose = DocumentPurpose.STUDY_MATERIAL
    #: Restrict to these documents. Empty means every ready document.
    document_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    #: Restrict to chunks under a heading containing this text, used by
    #: topic-scoped MCQ generation.
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One result, carrying the metadata that makes it traceable to its source.

    `score` is comparable only within the strategy that produced it — a cosine
    similarity and a text-rank score are different scales. Fusion therefore
    combines ranks rather than scores.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    content: str
    score: float
    rank: int
    page_number: int | None = None
    heading: str | None = None

    @property
    def source(self) -> str:
        """Human-readable citation, e.g. `notes.pdf, p. 7 — OSI Model`."""
        location = self.filename
        if self.page_number is not None:
            location = f"{location}, p. {self.page_number}"
        return f"{location} — {self.heading}" if self.heading else location


class Retriever(ABC):
    """A strategy for finding chunks relevant to a query."""

    #: Identifies the strategy in comparison output and logs.
    name: str

    @abstractmethod
    async def retrieve(self, query: RetrievalQuery, top_k: int) -> list[RetrievedChunk]:
        """Return at most `top_k` chunks, best first, with `rank` starting at 1."""


def rank_results(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Assign 1-based ranks in the order given.

    Ranks are what fusion consumes, so every retriever produces them the same
    way rather than each deciding whether to count from zero.
    """
    return [replace(chunk, rank=index) for index, chunk in enumerate(chunks, start=1)]
