"""Orchestrate extraction, normalization, embedding and clustering.

Generating FAQs needs no LLM call and writes nothing to the database — it only
reads chunks that ingestion already produced. That makes it cheap enough to
run fresh on every request rather than caching a result that would go stale
the moment a new past paper finishes ingesting.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import Chunk, Document
from examrag.embeddings.embedding_generator import EmbeddingGenerator
from examrag.enums import DocumentPurpose, ProcessingStatus
from examrag.faq.question_clusterer import DEFAULT_SIMILARITY_THRESHOLD, cluster_questions
from examrag.faq.question_extractor import ExtractedQuestion, SourceChunk, extract_questions
from examrag.faq.question_normalizer import normalize_question

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FaqSource:
    """Where one occurrence of a clustered question came from."""

    document_id: UUID
    filename: str
    page_number: int | None
    heading: str | None


@dataclass(frozen=True, slots=True)
class FaqCluster:
    """A question, in its clearest phrasing, and how often it recurs."""

    representative: str
    occurrence_count: int
    document_count: int
    variants: list[str]
    sources: list[FaqSource]


@dataclass(frozen=True, slots=True)
class FaqGenerationResult:
    """A generation run's totals alongside the clusters that survived filtering."""

    question_count: int
    document_count: int
    clusters: list[FaqCluster]


async def generate_faqs(
    session: AsyncSession,
    generator: EmbeddingGenerator,
    *,
    document_ids: Sequence[UUID] | None = None,
    min_occurrences: int = 1,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> FaqGenerationResult:
    """Extract, cluster and rank the questions found in past papers.

    Documents that are not `READY`, or not `PAST_PAPER`, are silently excluded
    — the same rule `retrieval/filters.py` applies: a document mid-ingestion
    has incomplete chunks, and study material is never a source of exam
    questions.

    Args:
        document_ids: Scope to these past papers, or every ready one when empty.
        min_occurrences: Drop clusters with fewer members than this. A cluster
            of one is not a "frequently asked" question.
    """
    chunks = await _past_paper_chunks(session, document_ids)
    extracted = extract_questions(chunks)
    if not extracted:
        return FaqGenerationResult(question_count=0, document_count=0, clusters=[])

    normalized = [normalize_question(item.text) for item in extracted]
    embeddings = generator.embed_texts(normalized)
    clusters = cluster_questions(embeddings, threshold=similarity_threshold)

    faqs = [
        _build_cluster(cluster.member_indices, extracted, normalized)
        for cluster in clusters
        if cluster.size >= min_occurrences
    ]
    faqs.sort(key=lambda faq: (faq.occurrence_count, faq.document_count), reverse=True)

    document_count = len({item.document_id for item in extracted})
    logger.info(
        "Extracted %d question(s) from %d past-paper chunk(s) across %d document(s) "
        "into %d cluster(s) at >= %d occurrence(s)",
        len(extracted),
        len(chunks),
        document_count,
        len(faqs),
        min_occurrences,
    )
    return FaqGenerationResult(
        question_count=len(extracted),
        document_count=document_count,
        clusters=faqs,
    )


async def _past_paper_chunks(
    session: AsyncSession, document_ids: Sequence[UUID] | None
) -> list[SourceChunk]:
    conditions = [
        Document.purpose == DocumentPurpose.PAST_PAPER,
        Document.status == ProcessingStatus.READY,
    ]
    if document_ids:
        conditions.append(Document.id.in_(document_ids))

    result = await session.execute(
        select(Chunk, Document.filename)
        .join(Document, Chunk.document_id == Document.id)
        .where(*conditions)
        .order_by(Document.id, Chunk.chunk_index)
    )
    return [
        SourceChunk(
            document_id=chunk.document_id,
            filename=filename,
            content=chunk.content,
            page_number=chunk.page_number,
            heading=chunk.heading,
        )
        for chunk, filename in result.all()
    ]


def _build_cluster(
    member_indices: list[int],
    extracted: list[ExtractedQuestion],
    normalized: list[str],
) -> FaqCluster:
    members = [extracted[index] for index in member_indices]
    texts = [normalized[index] for index in member_indices]

    # The longest phrasing tends to be the most complete one — a shorter
    # variant is more often a paraphrase or an OCR-trimmed repeat than a
    # meaningfully different question.
    representative = max(texts, key=len)
    variants = list(dict.fromkeys(text for text in texts if text != representative))

    sources = [
        FaqSource(
            document_id=member.document_id,
            filename=member.filename,
            page_number=member.page_number,
            heading=member.heading,
        )
        for member in members
    ]

    return FaqCluster(
        representative=representative,
        occurrence_count=len(members),
        document_count=len({source.document_id for source in sources}),
        variants=variants,
        sources=sources,
    )
