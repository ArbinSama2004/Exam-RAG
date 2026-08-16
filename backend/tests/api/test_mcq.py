"""Tests for quiz generation, answering and submission.

The property these exist to protect: the browser must not be able to learn a
correct answer before committing to one. Several tests check the raw response
body rather than a parsed field, because a leak would most likely arrive as an
extra key nobody meant to serialize.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.database.models import EMBEDDING_DIMENSIONS, Chunk, Document
from examrag.dependencies import get_llm_client, get_rag_pipeline
from examrag.enums import DocumentPurpose, DocumentType, ProcessingStatus
from examrag.main import create_app
from examrag.rag.context_builder import Context, ContextPassage

QUESTIONS = [
    {
        "question": "Which protocol provides reliable transport?",
        "options": ["HTTP", "IP", "TCP", "ARP"],
        "correct_index": 2,
        "explanation": "TCP is connection-oriented and retransmits lost segments.",
        "source": 1,
    },
    {
        "question": "What does IP guarantee?",
        "options": ["Ordering", "Delivery", "Encryption", "Nothing by itself"],
        "correct_index": 3,
        "explanation": "IP is best-effort.",
        "source": 1,
    },
]


class FakeLLM:
    """Returns a fixed set of questions without touching a model."""

    def __init__(self, questions: list[dict[str, Any]] | None = None) -> None:
        self.questions = QUESTIONS if questions is None else questions

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        return "An answer."

    async def complete_json(
        self, prompt: str, *, system: str | None = None
    ) -> dict[str, Any] | list[Any]:
        return {"questions": self.questions}


class FakePipeline:
    """Returns a fixed context, so no embedding or reranking model is needed."""

    async def build_context(self, query: object) -> Context:
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


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
async def api(db_session: AsyncSession, llm: FakeLLM) -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_rag_pipeline] = lambda: FakePipeline()
    app.dependency_overrides[get_llm_client] = lambda: llm

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def make_document(
    session: AsyncSession, status: ProcessingStatus = ProcessingStatus.READY
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        filename="networking.pdf",
        document_type=DocumentType.PDF,
        purpose=DocumentPurpose.STUDY_MATERIAL,
        status=status,
        stored_path=f"{uuid.uuid4()}.pdf",
        size_bytes=1024,
        original_file_hash=uuid.uuid4().hex,
    )
    document.chunks = [
        Chunk(
            chunk_index=0,
            content="TCP provides reliable transport.",
            char_count=32,
            heading="Transport Layer",
            embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
        )
    ]
    session.add(document)
    await session.flush()
    return document


async def generate(client: AsyncClient, document: Document, **overrides: Any):
    payload = {"document_ids": [str(document.id)], "count": 2, "difficulty": "MEDIUM"}
    payload.update(overrides)
    return await client.post("/quizzes/generate", json=payload)


class TestGeneration:
    async def test_a_quiz_is_generated_from_the_selected_documents(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)

        response = await generate(api, document)

        assert response.status_code == 201
        body = response.json()
        assert len(body["questions"]) == 2
        assert body["questions"][0]["question"].startswith("Which protocol")
        assert [question["position"] for question in body["questions"]] == [0, 1]

    async def test_the_generated_quiz_carries_no_answer_key(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point of server-side quizzes."""
        document = await make_document(db_session)

        response = await generate(api, document)

        for question in response.json()["questions"]:
            assert set(question) == {"id", "position", "question", "options"}

    async def test_the_answer_is_absent_from_the_raw_response_body(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A leak would most likely be an unexpected key, so check the bytes."""
        document = await make_document(db_session)

        body = (await generate(api, document)).text

        assert "correct_index" not in body
        assert "explanation" not in body
        # The correct answer text itself is an option, so only the key matters.
        assert "connection-oriented and retransmits" not in body

    async def test_documents_that_are_not_ready_are_rejected(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session, status=ProcessingStatus.PROCESSING)

        response = await generate(api, document)

        assert response.status_code == 400
        assert "not ready" in response.json()["detail"]

    async def test_an_unknown_document_is_rejected(self, api: AsyncClient) -> None:
        response = await api.post(
            "/quizzes/generate", json={"document_ids": [str(uuid.uuid4())], "count": 2}
        )

        assert response.status_code == 400

    async def test_at_least_one_document_is_required(self, api: AsyncClient) -> None:
        response = await api.post("/quizzes/generate", json={"document_ids": [], "count": 2})

        assert response.status_code == 422

    async def test_the_question_count_is_bounded(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)

        assert (await generate(api, document, count=0)).status_code == 422
        assert (await generate(api, document, count=500)).status_code == 422

    async def test_malformed_model_output_is_rejected(
        self, api: AsyncClient, db_session: AsyncSession, llm: FakeLLM
    ) -> None:
        """Three options, or an out-of-range index, is not a usable question."""
        llm.questions = [
            {"question": "Too few options?", "options": ["a", "b", "c"], "correct_index": 0},
            {"question": "Bad index?", "options": ["a", "b", "c", "d"], "correct_index": 9},
        ]
        document = await make_document(db_session)

        response = await generate(api, document)

        assert response.status_code == 422
        assert "Could not generate" in response.json()["detail"]

    async def test_duplicate_questions_are_dropped(
        self, api: AsyncClient, db_session: AsyncSession, llm: FakeLLM
    ) -> None:
        llm.questions = [QUESTIONS[0], dict(QUESTIONS[0]), QUESTIONS[1]]
        document = await make_document(db_session)

        body = (await generate(api, document, count=3)).json()

        questions = [question["question"] for question in body["questions"]]
        assert len(questions) == len(set(questions))


class TestAnswering:
    async def test_answering_reveals_the_correct_option(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()
        question = quiz["questions"][0]

        response = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": question["id"], "selected_index": 2},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["is_correct"] is True
        assert body["correct_index"] == 2
        assert body["explanation"].startswith("TCP is connection-oriented")
        assert body["source"] == "networking.pdf, p. 1 — Transport Layer"

    async def test_a_wrong_answer_is_graded_wrong(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()

        response = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 0},
        )

        assert response.json()["is_correct"] is False
        assert response.json()["correct_index"] == 2

    async def test_a_question_cannot_be_answered_twice(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise the endpoint becomes an oracle for the correct option."""
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()
        question_id = quiz["questions"][0]["id"]

        first = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": question_id, "selected_index": 0},
        )
        second = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": question_id, "selected_index": 1},
        )

        assert first.status_code == 200
        assert second.status_code == 409

    async def test_an_out_of_range_option_is_rejected(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()

        response = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 7},
        )

        assert response.status_code == 422

    async def test_a_question_from_another_quiz_is_rejected(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        first = (await generate(api, document)).json()
        second = (await generate(api, document)).json()

        response = await api.post(
            f"/quizzes/{first['id']}/answer",
            json={"question_id": second["questions"][0]["id"], "selected_index": 0},
        )

        assert response.status_code == 404

    async def test_answering_an_unknown_quiz_is_404(self, api: AsyncClient) -> None:
        response = await api.post(
            f"/quizzes/{uuid.uuid4()}/answer",
            json={"question_id": str(uuid.uuid4()), "selected_index": 0},
        )

        assert response.status_code == 404


class TestSubmission:
    async def test_the_score_counts_correct_answers(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()
        await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 2},
        )
        await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][1]["id"], "selected_index": 0},
        )

        result = (await api.post(f"/quizzes/{quiz['id']}/submit")).json()

        assert result["score"] == 1
        assert result["total"] == 2
        assert result["correct"] == 1
        assert result["incorrect"] == 1
        assert result["unanswered"] == 0

    async def test_unanswered_questions_are_counted(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()

        result = (await api.post(f"/quizzes/{quiz['id']}/submit")).json()

        assert result["unanswered"] == 2
        assert result["score"] == 0

    async def test_the_review_reveals_answers_and_sources(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()
        await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 0},
        )

        result = (await api.post(f"/quizzes/{quiz['id']}/submit")).json()

        wrong = next(item for item in result["questions"] if item["is_correct"] is False)
        assert wrong["selected_index"] == 0
        assert wrong["correct_index"] == 2
        assert wrong["explanation"]
        assert wrong["source"]

    async def test_answering_after_submission_is_refused(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()
        await api.post(f"/quizzes/{quiz['id']}/submit")

        response = await api.post(
            f"/quizzes/{quiz['id']}/answer",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 2},
        )

        assert response.status_code == 409

    async def test_submitting_twice_keeps_the_first_result(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()

        first = (await api.post(f"/quizzes/{quiz['id']}/submit")).json()
        second = (await api.post(f"/quizzes/{quiz['id']}/submit")).json()

        assert first["submitted_at"] == second["submitted_at"]

    async def test_submitting_an_unknown_quiz_is_404(self, api: AsyncClient) -> None:
        assert (await api.post(f"/quizzes/{uuid.uuid4()}/submit")).status_code == 404


class TestFetchingAQuizInProgress:
    async def test_refetching_still_hides_the_answer_key(
        self, api: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Reloading the page mid-quiz must not hand over the answers."""
        document = await make_document(db_session)
        quiz = (await generate(api, document)).json()

        body = (await api.get(f"/quizzes/{quiz['id']}")).text

        assert "correct_index" not in body
        assert "explanation" not in body

    async def test_an_unknown_quiz_is_404(self, api: AsyncClient) -> None:
        assert (await api.get(f"/quizzes/{uuid.uuid4()}")).status_code == 404
