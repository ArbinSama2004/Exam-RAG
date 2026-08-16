"""Quiz generation, answering and submission.

The answer key never leaves the server until the user has committed to an
answer. `POST /quizzes/generate` returns questions and options only; the
correct index is revealed by `POST /quizzes/{id}/answer`, after the choice is
recorded, and by `POST /quizzes/{id}/submit`.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from examrag.database.connection import get_session
from examrag.database.models import Document, Quiz, QuizAnswer, QuizQuestion
from examrag.dependencies import get_llm_client, get_rag_pipeline
from examrag.enums import ProcessingStatus
from examrag.generation.llm_client import LLMClient, LLMError
from examrag.generation.mcq_generator import MCQGenerationError, MCQGenerator, MCQRequest
from examrag.rag.pipeline import RagPipeline
from examrag.schemas.mcq import (
    AnswerRequest,
    AnswerResult,
    QuizGenerateRequest,
    QuizPublic,
    QuizQuestionPublic,
    QuizQuestionReview,
    QuizResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.post("/generate", response_model=QuizPublic, status_code=status.HTTP_201_CREATED)
async def generate_quiz(
    request: QuizGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    pipeline: Annotated[RagPipeline, Depends(get_rag_pipeline)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> QuizPublic:
    """Generate a quiz from the selected study material.

    Returns the questions and options. The correct answers stay on the server.
    """
    await _require_ready_documents(session, request.document_ids)

    mcq_request = MCQRequest(
        document_ids=frozenset(request.document_ids),
        count=request.count,
        difficulty=request.difficulty,
        topic=request.topic,
    )
    generator = MCQGenerator(session, pipeline, llm)

    # Retrieval first, then release the transaction: writing a quiz can take
    # minutes, and a database connection held open across those model calls
    # gets dropped while it sits idle.
    plans = await generator.plan(mcq_request)
    await session.commit()

    try:
        generated = await generator.generate(mcq_request, plans)
    except MCQGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    quiz = Quiz(
        document_ids=list(request.document_ids),
        difficulty=request.difficulty,
        topic=request.topic,
        question_count=len(generated),
    )
    quiz.questions = [
        QuizQuestion(
            position=position,
            question=item.question,
            options=item.options,
            correct_index=item.correct_index,
            explanation=item.explanation,
            source=item.source,
        )
        for position, item in enumerate(generated)
    ]
    session.add(quiz)
    await session.commit()
    await session.refresh(quiz, ["questions"])

    logger.info("Generated quiz %s with %d question(s)", quiz.id, len(quiz.questions))
    return _public(quiz)


@router.get("/{quiz_id}", response_model=QuizPublic)
async def get_quiz(
    quiz_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuizPublic:
    """Return a quiz in progress, still without its answer key."""
    return _public(await _require_quiz(session, quiz_id))


@router.post("/{quiz_id}/answer", response_model=AnswerResult)
async def submit_answer(
    quiz_id: uuid.UUID,
    request: AnswerRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnswerResult:
    """Record and grade one answer, then reveal the correct one.

    A question can only be answered once, so repeated calls cannot be used to
    search for the correct option.
    """
    quiz = await _require_quiz(session, quiz_id)
    if quiz.is_submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "This quiz has already been submitted.")

    question = next((q for q in quiz.questions if q.id == request.question_id), None)
    if question is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Question {request.question_id} is not in this quiz."
        )
    if not 0 <= request.selected_index < len(question.options):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"selected_index must be between 0 and {len(question.options) - 1}.",
        )

    existing = await session.scalar(select(QuizAnswer).where(QuizAnswer.question_id == question.id))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This question has already been answered.")

    is_correct = request.selected_index == question.correct_index
    session.add(
        QuizAnswer(
            quiz_id=quiz.id,
            question_id=question.id,
            selected_index=request.selected_index,
            is_correct=is_correct,
        )
    )
    await session.commit()

    return AnswerResult(
        question_id=question.id,
        selected_index=request.selected_index,
        correct_index=question.correct_index,
        is_correct=is_correct,
        explanation=question.explanation,
        source=question.source,
    )


@router.post("/{quiz_id}/submit", response_model=QuizResult)
async def submit_quiz(
    quiz_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuizResult:
    """Finish the quiz and return the score with a full review."""
    quiz = await _require_quiz(session, quiz_id)
    answers = {
        answer.question_id: answer
        for answer in await session.scalars(select(QuizAnswer).where(QuizAnswer.quiz_id == quiz.id))
    }

    if not quiz.is_submitted:
        quiz.submitted_at = datetime.now(UTC)
        await session.commit()

    review = [
        QuizQuestionReview(
            id=question.id,
            position=question.position,
            question=question.question,
            options=question.options,
            correct_index=question.correct_index,
            explanation=question.explanation,
            source=question.source,
            selected_index=(
                answers[question.id].selected_index if question.id in answers else None
            ),
            is_correct=answers[question.id].is_correct if question.id in answers else None,
        )
        for question in quiz.questions
    ]

    correct = sum(1 for item in review if item.is_correct is True)
    incorrect = sum(1 for item in review if item.is_correct is False)

    assert quiz.submitted_at is not None
    return QuizResult(
        quiz_id=quiz.id,
        score=correct,
        total=len(review),
        correct=correct,
        incorrect=incorrect,
        unanswered=len(review) - correct - incorrect,
        questions=review,
        submitted_at=quiz.submitted_at,
    )


def _public(quiz: Quiz) -> QuizPublic:
    """Build the answer-key-free view of a quiz."""
    return QuizPublic(
        id=quiz.id,
        difficulty=quiz.difficulty,
        topic=quiz.topic,
        question_count=quiz.question_count,
        questions=[QuizQuestionPublic.model_validate(question) for question in quiz.questions],
        created_at=quiz.created_at,
    )


async def _require_quiz(session: AsyncSession, quiz_id: uuid.UUID) -> Quiz:
    quiz = await session.scalar(
        select(Quiz).where(Quiz.id == quiz_id).options(selectinload(Quiz.questions))
    )
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No quiz with id {quiz_id}.")
    return quiz


async def _require_ready_documents(session: AsyncSession, document_ids: list[uuid.UUID]) -> None:
    """Reject documents that are missing or not finished ingesting."""
    ready = set(
        await session.scalars(
            select(Document.id).where(
                Document.id.in_(document_ids),
                Document.status == ProcessingStatus.READY,
            )
        )
    )
    missing = [str(document_id) for document_id in document_ids if document_id not in ready]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"These documents are not ready for retrieval: {', '.join(missing)}",
        )
