"""Vector and keyword search against a real PostgreSQL database."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk, Document
from examrag.embeddings.embedding_generator import EmbeddingGenerator
from examrag.enums import DocumentPurpose, DocumentType, ProcessingStatus
from examrag.retrieval.base import RetrievalQuery
from examrag.retrieval.keyword_search import KeywordRetriever
from examrag.retrieval.vector_search import VectorRetriever

#: Distinct unit vectors, so cosine distance is predictable.
AXES = {
    "tcp": 0,
    "ip": 1,
    "unrelated": 2,
    "query": 0,  # aligned with "tcp"
}


def vector(axis: str) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[AXES[axis]] = 1.0
    return values


class AxisEncoder:
    """Embeds a query to whichever axis its text names."""

    def encode(self, sentences, batch_size=32, normalize_embeddings=False, **_):
        return [vector(text if text in AXES else "unrelated") for text in sentences]

    def get_embedding_dimension(self) -> int:
        return EMBEDDING_DIMENSIONS


@pytest.fixture
def generator() -> EmbeddingGenerator:
    return EmbeddingGenerator(encoder=AxisEncoder())


async def make_corpus(
    session: AsyncSession,
    purpose: DocumentPurpose = DocumentPurpose.STUDY_MATERIAL,
    status: ProcessingStatus = ProcessingStatus.READY,
) -> Document:
    """A ready document with three distinguishable chunks."""
    document = Document(
        id=uuid.uuid4(),
        filename="networking.pdf",
        document_type=DocumentType.PDF,
        purpose=purpose,
        status=status,
        stored_path=f"{uuid.uuid4()}.pdf",
        size_bytes=1024,
        original_file_hash=uuid.uuid4().hex,
    )
    document.chunks = [
        Chunk(
            chunk_index=0,
            content="TCP provides reliable connection-oriented transport.",
            char_count=52,
            page_number=1,
            heading="Transport Layer",
            embedding=vector("tcp"),
        ),
        Chunk(
            chunk_index=1,
            content="IP routes packets between networks.",
            char_count=35,
            page_number=2,
            heading="Network Layer",
            embedding=vector("ip"),
        ),
        Chunk(
            chunk_index=2,
            content="Photosynthesis converts light into chemical energy.",
            char_count=51,
            page_number=3,
            heading="Biology",
            embedding=vector("unrelated"),
        ),
    ]
    session.add(document)
    await session.flush()
    return document


class TestVectorSearch:
    async def test_the_closest_chunk_ranks_first(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        document = await make_corpus(db_session)
        retriever = VectorRetriever(db_session, generator)

        results = await retriever.retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({document.id})), top_k=3
        )

        assert results[0].content.startswith("TCP provides")
        assert results[0].rank == 1

    async def test_similarity_is_reported_not_distance(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        document = await make_corpus(db_session)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({document.id})), top_k=1
        )

        # Identical vectors: cosine distance 0, so similarity 1.
        assert results[0].score == pytest.approx(1.0)

    async def test_metadata_comes_back_with_the_chunk(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        document = await make_corpus(db_session)

        top = (
            await VectorRetriever(db_session, generator).retrieve(
                RetrievalQuery(text="tcp", document_ids=frozenset({document.id})), top_k=1
            )
        )[0]

        assert top.filename == "networking.pdf"
        assert top.page_number == 1
        assert top.heading == "Transport Layer"
        assert top.source == "networking.pdf, p. 1 — Transport Layer"

    async def test_top_k_is_respected(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        document = await make_corpus(db_session)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({document.id})), top_k=2
        )

        assert len(results) == 2

    async def test_an_empty_query_retrieves_nothing(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        await make_corpus(db_session)

        assert (
            await VectorRetriever(db_session, generator).retrieve(
                RetrievalQuery(text="   "), top_k=5
            )
            == []
        )


class TestKeywordSearch:
    async def test_an_exact_term_is_found(self, db_session: AsyncSession) -> None:
        document = await make_corpus(db_session)

        results = await KeywordRetriever(db_session).retrieve(
            RetrievalQuery(text="photosynthesis", document_ids=frozenset({document.id})),
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].content.startswith("Photosynthesis")

    async def test_chunks_without_the_terms_are_excluded(self, db_session: AsyncSession) -> None:
        """Unlike vector search, keyword search returns nothing rather than the nearest miss."""
        document = await make_corpus(db_session)

        results = await KeywordRetriever(db_session).retrieve(
            RetrievalQuery(text="quantum entanglement", document_ids=frozenset({document.id})),
            top_k=5,
        )

        assert results == []

    async def test_search_operators_do_not_crash_the_query(self, db_session: AsyncSession) -> None:
        """websearch_to_tsquery must swallow whatever a user types."""
        document = await make_corpus(db_session)

        for text in ['"reliable transport"', "TCP or IP", "packets -biology", "((("]:
            await KeywordRetriever(db_session).retrieve(
                RetrievalQuery(text=text, document_ids=frozenset({document.id})), top_k=5
            )

    async def test_ranks_start_at_one(self, db_session: AsyncSession) -> None:
        document = await make_corpus(db_session)

        results = await KeywordRetriever(db_session).retrieve(
            RetrievalQuery(text="networks or transport", document_ids=frozenset({document.id})),
            top_k=5,
        )

        assert [item.rank for item in results] == list(range(1, len(results) + 1))


class TestSharedFilters:
    async def test_past_papers_are_not_returned_as_answer_evidence(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        """The specification's hardest rule: past papers are not study material."""
        paper = await make_corpus(db_session, purpose=DocumentPurpose.PAST_PAPER)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({paper.id})), top_k=5
        )

        assert results == []

    async def test_past_papers_are_returned_when_asked_for(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        paper = await make_corpus(db_session, purpose=DocumentPurpose.PAST_PAPER)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(
                text="tcp",
                purpose=DocumentPurpose.PAST_PAPER,
                document_ids=frozenset({paper.id}),
            ),
            top_k=5,
        )

        assert results

    async def test_documents_still_processing_are_excluded(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        """Partial chunks would cite a source that is not finished."""
        document = await make_corpus(db_session, status=ProcessingStatus.PROCESSING)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({document.id})), top_k=5
        )

        assert results == []

    async def test_search_can_be_scoped_to_a_heading(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        document = await make_corpus(db_session)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(
                text="tcp", document_ids=frozenset({document.id}), heading="Network Layer"
            ),
            top_k=5,
        )

        assert {item.heading for item in results} == {"Network Layer"}

    async def test_other_documents_are_excluded_when_ids_are_given(
        self, db_session: AsyncSession, generator: EmbeddingGenerator
    ) -> None:
        wanted = await make_corpus(db_session)
        await make_corpus(db_session)

        results = await VectorRetriever(db_session, generator).retrieve(
            RetrievalQuery(text="tcp", document_ids=frozenset({wanted.id})), top_k=10
        )

        assert {item.document_id for item in results} == {wanted.id}
