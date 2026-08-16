"""Tests for MCQ generation, section distribution and output validation."""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk, Document
from examrag.enums import Difficulty, DocumentPurpose, DocumentType, ProcessingStatus
from examrag.generation.llm_client import LLMError
from examrag.generation.mcq_generator import (
    MCQGenerationError,
    MCQGenerator,
    MCQRequest,
    _allocate,
    _top_level_sections,
)
from examrag.rag.context_builder import Context, ContextPassage
from examrag.retrieval.base import RetrievalQuery


async def run(generator: MCQGenerator, request: MCQRequest):
    """Run both phases, as the endpoint does."""
    return await generator.generate(request, await generator.plan(request))


def valid_question(text: str = "Which protocol is reliable?") -> dict[str, Any]:
    return {
        "question": text,
        "options": ["HTTP", "IP", "TCP", "ARP"],
        "correct_index": 2,
        "explanation": "TCP retransmits lost segments.",
        "source": 1,
    }


class RecordingPipeline:
    """Captures the queries it is asked to retrieve for."""

    def __init__(self, empty: bool = False) -> None:
        self.queries: list[RetrievalQuery] = []
        self.empty = empty

    async def build_context(self, query: RetrievalQuery) -> Context:
        self.queries.append(query)
        if self.empty:
            return Context(passages=[])
        return Context(
            passages=[
                ContextPassage(
                    number=1,
                    text="TCP provides reliable transport.",
                    source="networking.pdf, p. 1 — Transport Layer",
                    chunk_id=str(uuid.uuid4()),
                    document_id=str(uuid.uuid4()),
                )
            ]
        )


class ScriptedLLM:
    """Returns a fixed payload, or raises, and records the prompts it saw."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload if payload is not None else {"questions": [valid_question()]}
        self.error = error
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        return "answer"

    async def complete_json(self, prompt: str, *, system: str | None = None) -> Any:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.payload


async def make_document(session: AsyncSession, headings: list[str]) -> Document:
    document = Document(
        id=uuid.uuid4(),
        filename="networking.pdf",
        document_type=DocumentType.PDF,
        purpose=DocumentPurpose.STUDY_MATERIAL,
        status=ProcessingStatus.READY,
        stored_path=f"{uuid.uuid4()}.pdf",
        size_bytes=1024,
        original_file_hash=uuid.uuid4().hex,
    )
    document.chunks = [
        Chunk(
            chunk_index=index,
            content=f"Content for {heading}.",
            char_count=20,
            heading=heading,
            embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
        )
        for index, heading in enumerate(headings)
    ]
    session.add(document)
    await session.flush()
    return document


class TestSectionDistribution:
    async def test_all_topics_retrieves_per_section(self, db_session: AsyncSession) -> None:
        """The specification forbids generating every question from one context."""
        document = await make_document(
            db_session,
            ["Networking > Transport Layer", "Networking > Network Layer", "Networking > Physical"],
        )
        pipeline = RecordingPipeline()
        generator = MCQGenerator(db_session, pipeline, ScriptedLLM())

        await run(generator, MCQRequest(document_ids=frozenset({document.id}), count=3, topic=None))

        headings = {query.heading for query in pipeline.queries}
        assert headings == {
            "Networking > Transport Layer",
            "Networking > Network Layer",
            "Networking > Physical",
        }

    async def test_a_chosen_topic_uses_one_scoped_retrieval(self, db_session: AsyncSession) -> None:
        document = await make_document(db_session, ["Networking > Transport Layer"])
        pipeline = RecordingPipeline()
        generator = MCQGenerator(db_session, pipeline, ScriptedLLM())

        await run(
            generator,
            MCQRequest(document_ids=frozenset({document.id}), count=5, topic="Transport Layer"),
        )

        assert len(pipeline.queries) == 1
        assert pipeline.queries[0].heading == "Transport Layer"

    async def test_a_document_without_headings_falls_back_to_one_context(
        self, db_session: AsyncSession
    ) -> None:
        """An unstructured document has no sections to distribute across."""
        document = await make_document(db_session, [])
        document.chunks = [Chunk(chunk_index=0, content="Plain text.", char_count=11, heading=None)]
        await db_session.flush()
        pipeline = RecordingPipeline()

        await run(
            MCQGenerator(db_session, pipeline, ScriptedLLM()),
            MCQRequest(document_ids=frozenset({document.id}), count=3),
        )

        assert len(pipeline.queries) == 1
        assert pipeline.queries[0].heading is None

    async def test_retrieval_is_scoped_to_the_requested_documents(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A > B"])
        pipeline = RecordingPipeline()

        await run(
            MCQGenerator(db_session, pipeline, ScriptedLLM()),
            MCQRequest(document_ids=frozenset({document.id}), count=1),
        )

        assert pipeline.queries[0].document_ids == frozenset({document.id})


class TestAllocation:
    def test_questions_spread_evenly_across_sections(self) -> None:
        assert _allocate(["a", "b", "c"], 6) == [("a", 2), ("b", 2), ("c", 2)]

    def test_the_remainder_goes_to_the_earliest_sections(self) -> None:
        assert _allocate(["a", "b", "c"], 7) == [("a", 3), ("b", 2), ("c", 2)]

    def test_fewer_questions_than_sections_uses_the_first_sections(self) -> None:
        assert _allocate(["a", "b", "c"], 2) == [("a", 1), ("b", 1)]

    def test_parent_headings_are_dropped_in_favour_of_their_children(self) -> None:
        headings = ["OSI", "OSI > Physical", "OSI > Transport"]

        assert _top_level_sections(headings) == ["OSI > Physical", "OSI > Transport"]

    def test_a_heading_with_no_children_is_kept(self) -> None:
        assert _top_level_sections(["Introduction"]) == ["Introduction"]


class TestValidation:
    async def test_a_question_with_the_wrong_option_count_is_discarded(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A"])
        bad = {**valid_question(), "options": ["a", "b", "c"]}
        llm = ScriptedLLM({"questions": [bad, valid_question()]})

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), llm),
            MCQRequest(document_ids=frozenset({document.id}), count=5),
        )

        assert len(questions) == 1

    async def test_duplicate_options_are_discarded(self, db_session: AsyncSession) -> None:
        document = await make_document(db_session, ["A"])
        bad = {**valid_question(), "options": ["TCP", "TCP", "IP", "ARP"]}
        llm = ScriptedLLM({"questions": [bad]})

        with pytest.raises(MCQGenerationError):
            await run(
                MCQGenerator(db_session, RecordingPipeline(), llm),
                MCQRequest(document_ids=frozenset({document.id}), count=1),
            )

    async def test_an_out_of_range_correct_index_is_discarded(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM({"questions": [{**valid_question(), "correct_index": 9}]})

        with pytest.raises(MCQGenerationError):
            await run(
                MCQGenerator(db_session, RecordingPipeline(), llm),
                MCQRequest(document_ids=frozenset({document.id}), count=1),
            )

    async def test_a_bare_array_is_accepted(self, db_session: AsyncSession) -> None:
        """Small models sometimes drop the wrapper object."""
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM([valid_question()])

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), llm),
            MCQRequest(document_ids=frozenset({document.id}), count=1),
        )

        assert len(questions) == 1

    async def test_the_passage_citation_becomes_a_real_source(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A"])

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), ScriptedLLM()),
            MCQRequest(document_ids=frozenset({document.id}), count=1),
        )

        assert questions[0].source == "networking.pdf, p. 1 — Transport Layer"

    async def test_an_invalid_citation_falls_back_rather_than_misattributing(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM({"questions": [{**valid_question(), "source": 99}]})

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), llm),
            MCQRequest(document_ids=frozenset({document.id}), count=1),
        )

        assert questions[0].source == "networking.pdf, p. 1 — Transport Layer"

    async def test_a_missing_explanation_gets_a_placeholder(self, db_session: AsyncSession) -> None:
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM({"questions": [{**valid_question(), "explanation": ""}]})

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), llm),
            MCQRequest(document_ids=frozenset({document.id}), count=1),
        )

        assert questions[0].explanation


class TestFailures:
    async def test_a_model_failure_in_one_section_does_not_lose_the_quiz(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A > One", "A > Two"])

        class FlakyLLM(ScriptedLLM):
            calls = 0

            async def complete_json(self, prompt: str, *, system: str | None = None) -> Any:
                FlakyLLM.calls += 1
                if FlakyLLM.calls == 1:
                    raise LLMError("model hiccup")
                return {"questions": [valid_question()]}

        questions = await run(
            MCQGenerator(db_session, RecordingPipeline(), FlakyLLM()),
            MCQRequest(document_ids=frozenset({document.id}), count=2),
        )

        assert len(questions) == 1

    async def test_failing_everywhere_reports_the_model_error(
        self, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM(error=LLMError("Ollama is unreachable"))

        with pytest.raises(MCQGenerationError, match="Ollama is unreachable"):
            await run(
                MCQGenerator(db_session, RecordingPipeline(), llm),
                MCQRequest(document_ids=frozenset({document.id}), count=2),
            )

    async def test_no_retrievable_context_yields_no_questions(
        self, db_session: AsyncSession
    ) -> None:
        """Generating from nothing is how a RAG application starts inventing facts."""
        document = await make_document(db_session, ["A"])
        llm = ScriptedLLM()

        with pytest.raises(MCQGenerationError):
            await run(
                MCQGenerator(db_session, RecordingPipeline(empty=True), llm),
                MCQRequest(document_ids=frozenset({document.id}), count=2),
            )

        assert llm.prompts == []

    async def test_requesting_no_questions_returns_nothing(self, db_session: AsyncSession) -> None:
        document = await make_document(db_session, ["A"])

        result = await run(
            MCQGenerator(db_session, RecordingPipeline(), ScriptedLLM()),
            MCQRequest(document_ids=frozenset({document.id}), count=0),
        )

        assert result == []


async def test_difficulty_reaches_the_prompt(db_session: AsyncSession) -> None:
    document = await make_document(db_session, ["A"])
    llm = ScriptedLLM()

    await run(
        MCQGenerator(db_session, RecordingPipeline(), llm),
        MCQRequest(document_ids=frozenset({document.id}), count=1, difficulty=Difficulty.HARD),
    )

    assert "hard difficulty" in llm.prompts[0]
