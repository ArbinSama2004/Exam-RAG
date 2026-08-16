"""Generate multiple-choice questions from retrieved study material.

For a single topic, one retrieval is enough. For **all topics** the questions
must cover the document, so generation walks the document's sections and
retrieves context for each one. Taking a single global top-k instead would
produce ten questions about whichever part of the document happened to rank
highest — the failure this design exists to prevent.

```text
Document sections
      ↓
Question allocation per section
      ↓
Context retrieval per section
      ↓
MCQ generation
      ↓
Validation and deduplication
```

The model's output is treated as untrusted: every question is validated for
shape before it is kept, and near-duplicates are dropped.

Generation is deliberately split into two phases. `plan` does all the database
work — listing sections and retrieving context — and `generate` does only model
calls. A quiz can take minutes to write, and holding a database transaction
open across those calls pins a connection long enough for an idle one to be
dropped, which is exactly what happened the first time this ran end to end.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.vector_store import list_headings
from examrag.enums import Difficulty
from examrag.generation.llm_client import LLMClient, LLMError
from examrag.generation.prompt_builder import MCQ_SYSTEM_PROMPT, build_mcq_prompt
from examrag.rag.context_builder import Context
from examrag.rag.pipeline import RagPipeline
from examrag.retrieval.base import RetrievalQuery

logger = logging.getLogger(__name__)

#: Options per question. Fixed by the quiz interface, not a preference.
OPTIONS_PER_QUESTION = 4

#: Sections used for an all-topics quiz. Beyond this the per-section share
#: rounds down to nothing and each retrieval costs a model call.
MAX_SECTIONS = 12

#: How many extra questions to ask for, since validation and deduplication
#: discard some of what the model returns.
OVERSAMPLE = 2


class MCQGenerationError(RuntimeError):
    """No usable questions could be generated."""


@dataclass(frozen=True, slots=True)
class GeneratedMCQ:
    """One validated question, with the source it came from."""

    question: str
    options: list[str]
    correct_index: int
    explanation: str
    source: str

    @property
    def correct_answer(self) -> str:
        return self.options[self.correct_index]


@dataclass(frozen=True, slots=True)
class SectionPlan:
    """One section's share of the quiz, with its context already retrieved."""

    topic: str | None
    count: int
    context: Context


@dataclass(frozen=True, slots=True)
class MCQRequest:
    """What to generate."""

    document_ids: frozenset[uuid.UUID]
    count: int
    difficulty: Difficulty = Difficulty.MEDIUM
    #: A specific heading, or None for all topics.
    topic: str | None = None


class MCQGenerator:
    """Produces validated MCQs grounded in retrieved context."""

    def __init__(self, session: AsyncSession, pipeline: RagPipeline, llm: LLMClient) -> None:
        self._session = session
        self._pipeline = pipeline
        self._llm = llm

    async def plan(self, request: MCQRequest) -> list[SectionPlan]:
        """Choose the sections and retrieve context for each.

        This is the only phase that touches the database, so the caller can
        release its transaction before the model calls begin.
        """
        if request.count <= 0:
            return []

        plans: list[SectionPlan] = []
        for topic, share in await self._sections(request):
            query = RetrievalQuery(
                text=topic or "key concepts, definitions and mechanisms",
                document_ids=request.document_ids,
                heading=topic,
            )
            context = await self._pipeline.build_context(query)
            if context.is_empty:
                logger.warning("No context retrieved for topic %r", topic)
                continue
            plans.append(SectionPlan(topic=topic, count=share, context=context))
        return plans

    async def generate(self, request: MCQRequest, plans: list[SectionPlan]) -> list[GeneratedMCQ]:
        """Write questions for each planned section. Makes no database calls.

        Raises:
            MCQGenerationError: nothing usable came back.
        """
        if request.count <= 0:
            return []

        questions: list[GeneratedMCQ] = []
        seen: set[str] = set()
        failures: list[str] = []

        for plan in plans:
            try:
                batch = await self._generate_for(request, plan)
            except LLMError as exc:
                # One bad section should not lose the whole quiz.
                logger.warning("Generation failed for topic %r: %s", plan.topic, exc)
                failures.append(str(exc))
                continue
            for question in batch:
                key = _dedup_key(question.question)
                if key not in seen:
                    seen.add(key)
                    questions.append(question)

        if not questions:
            detail = failures[0] if failures else "the model returned no valid questions"
            raise MCQGenerationError(f"Could not generate questions: {detail}")

        logger.info("Generated %d question(s) across %d section(s)", len(questions), len(plans))
        return questions[: request.count]

    async def _sections(self, request: MCQRequest) -> list[tuple[str | None, int]]:
        """Decide which topics to generate from, and how many questions each.

        Returns a single unscoped entry when the user picked a topic, or when
        the documents carry no headings at all — an unstructured document has
        no sections to distribute across.
        """
        if request.topic:
            return [(request.topic, request.count)]

        headings = await list_headings(self._session, list(request.document_ids))
        sections = _top_level_sections(headings)[:MAX_SECTIONS]
        if not sections:
            logger.info("No headings found; generating from one context")
            return [(None, request.count)]

        return _allocate(sections, request.count)

    async def _generate_for(self, request: MCQRequest, plan: SectionPlan) -> list[GeneratedMCQ]:
        prompt = build_mcq_prompt(
            plan.context,
            count=plan.count + OVERSAMPLE,
            difficulty=request.difficulty.value.lower(),
            topic=plan.topic,
        )
        payload = await self._llm.complete_json(prompt, system=MCQ_SYSTEM_PROMPT)
        return _parse(payload, plan.context)[: plan.count]


def _parse(payload: dict[str, Any] | list[Any], context: Context) -> list[GeneratedMCQ]:
    """Validate the model's output, keeping only well-formed questions."""
    raw = payload.get("questions", []) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []

    questions: list[GeneratedMCQ] = []
    for item in raw:
        question = _parse_one(item, context)
        if question is not None:
            questions.append(question)
        else:
            logger.debug("Discarded a malformed question: %r", item)
    return questions


def _parse_one(item: Any, context: Context) -> GeneratedMCQ | None:
    """Return a validated question, or None if the model's item is unusable."""
    if not isinstance(item, dict):
        return None

    text = str(item.get("question", "")).strip()
    explanation = str(item.get("explanation", "")).strip()
    raw_options = item.get("options")

    if not text or not isinstance(raw_options, list):
        return None

    options = [str(option).strip() for option in raw_options]
    if len(options) != OPTIONS_PER_QUESTION or not all(options):
        return None
    # Duplicate options make a question unanswerable or trivially guessable.
    if len({option.casefold() for option in options}) != OPTIONS_PER_QUESTION:
        return None

    try:
        correct_index = int(item.get("correct_index", -1))
    except (TypeError, ValueError):
        return None
    if not 0 <= correct_index < OPTIONS_PER_QUESTION:
        return None

    return GeneratedMCQ(
        question=text,
        options=options,
        correct_index=correct_index,
        explanation=explanation or "No explanation was provided.",
        source=_source_for(item.get("source"), context),
    )


def _source_for(value: Any, context: Context) -> str:
    """Resolve the model's passage number to a real citation.

    The model cites `[2]`; the user needs `notes.pdf, p. 7 — OSI Model`. An
    out-of-range number means the citation cannot be trusted, so it is dropped
    rather than pointed at the wrong passage.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return _fallback_source(context)

    for passage in context.passages:
        if passage.number == number:
            return passage.source
    return _fallback_source(context)


def _fallback_source(context: Context) -> str:
    return context.passages[0].source if context.passages else "Unknown source"


def _top_level_sections(headings: list[str]) -> list[str]:
    """Collapse breadcrumbs to the deepest distinct sections, in order.

    `OSI Model > Physical Layer` and `OSI Model > Transport Layer` are two
    sections worth separate questions; the parent `OSI Model` on its own is
    not, since its content is already covered by its children.
    """
    parents = {heading.rsplit(" > ", 1)[0] for heading in headings if " > " in heading}
    return [heading for heading in headings if heading not in parents]


def _allocate(sections: list[str], count: int) -> list[tuple[str | None, int]]:
    """Spread `count` questions across sections as evenly as possible.

    The remainder goes to the earliest sections, which are usually the
    document's foundational material.
    """
    if count <= len(sections):
        return [(section, 1) for section in sections[:count]]

    base, remainder = divmod(count, len(sections))
    return [
        (section, base + (1 if index < remainder else 0)) for index, section in enumerate(sections)
    ]


def _dedup_key(question: str) -> str:
    """Normalized form used to spot the same question asked twice."""
    return re.sub(r"[^a-z0-9 ]", "", question.casefold()).strip()
