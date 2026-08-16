"""Answer a question from retrieved study material.

This is the plain RAG path: retrieve, build context, prompt, generate. The FAQ
feature reuses it in Phase 3 to answer a selected frequently-asked question.

The sources are returned alongside the answer so the user can check it, rather
than being asked to trust prose that cites `[1]` with no way to see what `[1]`
was.
"""

import logging
import uuid
from dataclasses import dataclass

from examrag.generation.llm_client import LLMClient
from examrag.generation.prompt_builder import ANSWER_SYSTEM_PROMPT, build_answer_prompt
from examrag.rag.context_builder import ContextPassage
from examrag.rag.pipeline import RagPipeline
from examrag.retrieval.base import RetrievalQuery

logger = logging.getLogger(__name__)

#: Returned when retrieval finds nothing, instead of asking the model to answer
#: from no evidence — which is how a RAG application starts hallucinating.
NO_CONTEXT_ANSWER = (
    "I could not find anything about this in your uploaded study material. "
    "Try uploading a document that covers it, or rephrasing the question."
)


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """An answer and the passages it was generated from."""

    question: str
    answer: str
    passages: list[ContextPassage]
    model: str

    @property
    def is_grounded(self) -> bool:
        """False when nothing was retrieved, so the answer cites no source."""
        return bool(self.passages)


class AnswerGenerator:
    """Generates answers grounded in the user's study material."""

    def __init__(self, pipeline: RagPipeline, llm: LLMClient) -> None:
        self._pipeline = pipeline
        self._llm = llm

    async def answer(
        self, question: str, document_ids: frozenset[uuid.UUID] = frozenset()
    ) -> GeneratedAnswer:
        """Retrieve context for `question` and generate an answer from it."""
        context = await self._pipeline.build_context(
            RetrievalQuery(text=question, document_ids=document_ids)
        )

        if context.is_empty:
            logger.info("No context retrieved for %r; not calling the model", question)
            return GeneratedAnswer(
                question=question,
                answer=NO_CONTEXT_ANSWER,
                passages=[],
                model=self._llm.model_name,
            )

        text = await self._llm.complete(
            build_answer_prompt(question, context), system=ANSWER_SYSTEM_PROMPT
        )
        return GeneratedAnswer(
            question=question,
            answer=text,
            passages=context.passages,
            model=self._llm.model_name,
        )
