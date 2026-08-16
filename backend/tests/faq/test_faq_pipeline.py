"""Tests for the FAQ pipeline's database query and orchestration.

A `HashEncoder` stands in for the real model: identical normalized text always
produces an identical vector, so clustering behaves predictably without a
download. Whether real paraphrases actually cluster together is answered by
the opt-in evaluation in test_clustering_evaluation.py.
"""

import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import Chunk, Document
from examrag.embeddings.embedding_generator import EMBEDDING_DIMENSIONS, EmbeddingGenerator
from examrag.enums import DocumentPurpose, ProcessingStatus
from examrag.faq.faq_pipeline import FaqGenerationResult, generate_faqs
from examrag.faq.question_clusterer import QuestionCluster

from ..database.test_schema_integration import make_document

QUESTION = "1. Explain the OSI model in detail. [10 marks]"


class HashEncoder:
    """Deterministic stand-in for the real model: identical text, identical vector."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        show_progress_bar: bool = False,
    ) -> list[list[float]]:
        vectors = []
        for text in sentences:
            vector = [0.0] * self.dimensions
            index = int(hashlib.sha256(text.encode()).hexdigest(), 16) % self.dimensions
            vector[index] = 1.0
            vectors.append(vector)
        return vectors

    def get_embedding_dimension(self) -> int | None:
        return self.dimensions


def generator() -> EmbeddingGenerator:
    return EmbeddingGenerator(encoder=HashEncoder())


def past_paper(**overrides: object) -> Document:
    overrides.setdefault("purpose", DocumentPurpose.PAST_PAPER)
    overrides.setdefault("status", ProcessingStatus.READY)
    return make_document(**overrides)


def chunk(content: str, index: int = 0, page_number: int | None = 1) -> Chunk:
    return Chunk(
        chunk_index=index, content=content, char_count=len(content), page_number=page_number
    )


async def test_extracts_and_clusters_repeated_questions(db_session: AsyncSession) -> None:
    paper_2023 = past_paper(filename="2023.pdf")
    paper_2024 = past_paper(filename="2024.pdf")
    paper_2023.chunks = [chunk(QUESTION)]
    paper_2024.chunks = [chunk(QUESTION)]
    db_session.add_all([paper_2023, paper_2024])
    await db_session.flush()

    result = await generate_faqs(db_session, generator())

    assert result.question_count == 2
    assert result.document_count == 2
    assert len(result.clusters) == 1
    assert result.clusters[0].occurrence_count == 2
    assert result.clusters[0].document_count == 2
    assert result.clusters[0].representative == "Explain the OSI model in detail."


async def test_study_material_is_never_a_source(db_session: AsyncSession) -> None:
    study = make_document(purpose=DocumentPurpose.STUDY_MATERIAL, status=ProcessingStatus.READY)
    study.chunks = [chunk(QUESTION)]
    db_session.add(study)
    await db_session.flush()

    result = await generate_faqs(db_session, generator())

    assert result == FaqGenerationResult(question_count=0, document_count=0, clusters=[])


async def test_documents_still_ingesting_are_excluded(db_session: AsyncSession) -> None:
    unfinished = past_paper(status=ProcessingStatus.PROCESSING)
    unfinished.chunks = [chunk(QUESTION)]
    db_session.add(unfinished)
    await db_session.flush()

    result = await generate_faqs(db_session, generator())

    assert result.question_count == 0


async def test_min_occurrences_filters_singleton_clusters(db_session: AsyncSession) -> None:
    paper = past_paper()
    paper.chunks = [chunk(QUESTION)]
    db_session.add(paper)
    await db_session.flush()

    strict = await generate_faqs(db_session, generator(), min_occurrences=2)
    permissive = await generate_faqs(db_session, generator(), min_occurrences=1)

    assert strict.clusters == []
    assert len(permissive.clusters) == 1
    assert permissive.clusters[0].occurrence_count == 1


async def test_can_be_scoped_to_specific_documents(db_session: AsyncSession) -> None:
    included = past_paper(filename="included.pdf")
    excluded = past_paper(filename="excluded.pdf")
    included.chunks = [chunk(QUESTION)]
    excluded.chunks = [chunk(QUESTION)]
    db_session.add_all([included, excluded])
    await db_session.flush()

    result = await generate_faqs(
        db_session, generator(), document_ids=[included.id], min_occurrences=1
    )

    assert result.question_count == 1
    assert result.clusters[0].sources[0].filename == "included.pdf"


async def test_no_past_papers_returns_an_empty_result(db_session: AsyncSession) -> None:
    result = await generate_faqs(db_session, generator())

    assert result == FaqGenerationResult(question_count=0, document_count=0, clusters=[])


async def test_variants_exclude_the_representative(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_2023 = past_paper(filename="2023.pdf")
    paper_2024 = past_paper(filename="2024.pdf")
    paper_2023.chunks = [chunk("1. Explain the OSI model. [10 marks]")]
    paper_2024.chunks = [chunk("1. Explain the OSI model in full detail. [10 marks]")]
    db_session.add_all([paper_2023, paper_2024])
    await db_session.flush()

    # The two questions normalize to different text, so a HashEncoder alone
    # would not merge them — force the merge to check representative/variant
    # selection independently of clustering.
    def force_one_cluster(embeddings: list[list[float]], **_: object) -> list[QuestionCluster]:
        return [QuestionCluster(member_indices=list(range(len(embeddings))))]

    monkeypatch.setattr("examrag.faq.faq_pipeline.cluster_questions", force_one_cluster)

    result = await generate_faqs(db_session, generator(), min_occurrences=1)

    assert result.clusters[0].representative == "Explain the OSI model in full detail."
    assert result.clusters[0].variants == ["Explain the OSI model."]
