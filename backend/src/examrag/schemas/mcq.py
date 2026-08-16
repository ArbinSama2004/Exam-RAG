"""Request and response schemas for quiz generation and answering.

The split between `QuizQuestionPublic` and `QuizQuestionReview` is the point of
this module: the first is what the browser may see while the quiz is in
progress, and it has no field that could carry the answer key. The second is
only ever built after an answer is submitted.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from examrag.enums import Difficulty


class QuizGenerateRequest(BaseModel):
    """What to generate a quiz from."""

    document_ids: list[uuid.UUID] = Field(min_length=1)
    count: int = Field(default=10, ge=1, le=30)
    difficulty: Difficulty = Difficulty.MEDIUM
    #: A specific section heading, or null to spread questions across all
    #: sections of the selected documents.
    topic: str | None = None


class QuizQuestionPublic(BaseModel):
    """A question as the browser receives it: no correct answer, no explanation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    question: str
    options: list[str]


class QuizPublic(BaseModel):
    """A generated quiz, without its answer key."""

    id: uuid.UUID
    difficulty: Difficulty
    topic: str | None
    question_count: int
    questions: list[QuizQuestionPublic]
    created_at: datetime


class AnswerRequest(BaseModel):
    """One submitted answer."""

    question_id: uuid.UUID
    selected_index: int = Field(ge=0)


class AnswerResult(BaseModel):
    """The verdict on one answer.

    The correct answer is revealed here because the user has already committed
    to theirs, which is what makes it safe to send.
    """

    question_id: uuid.UUID
    selected_index: int
    correct_index: int
    is_correct: bool
    explanation: str
    source: str


class QuizQuestionReview(BaseModel):
    """A question with its answer key, for review after submission."""

    id: uuid.UUID
    position: int
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    source: str
    selected_index: int | None = None
    is_correct: bool | None = None


class QuizResult(BaseModel):
    """The final score and full review."""

    quiz_id: uuid.UUID
    score: int
    total: int
    correct: int
    incorrect: int
    unanswered: int
    questions: list[QuizQuestionReview]
    submitted_at: datetime
