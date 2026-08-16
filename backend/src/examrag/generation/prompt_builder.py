"""Construct the prompts sent to the model.

Prompts live here rather than inline in the generators, so the wording that
decides answer quality is in one reviewable place and can be adjusted during
evaluation without touching generation logic.

Both prompts insist on grounding: the model answers from the numbered passages
it is given and says so when they are insufficient, rather than filling gaps
from memory.
"""

from examrag.rag.context_builder import Context

ANSWER_SYSTEM_PROMPT = (
    "You are a precise study assistant. You answer only from the numbered "
    "passages you are given. If they do not contain the answer, you say so "
    "plainly instead of guessing. You never invent facts, sources or citations."
)

MCQ_SYSTEM_PROMPT = (
    "You are an exam author. You write multiple-choice questions that test "
    "understanding of the material you are given, never trivia about its "
    "wording. Every question, correct answer and explanation must be "
    "supported by the passages provided."
)


def build_answer_prompt(question: str, context: Context) -> str:
    """Prompt for answering a question from retrieved context."""
    return f"""Answer the question using only the passages below.

Passages:
{context.render()}

Question: {question}

Rules:
- Use only information from the passages.
- Cite the passages you used as [1], [2] and so on.
- If the passages do not contain the answer, say exactly what is missing.
- Be direct and concise.

Answer:"""


def build_mcq_prompt(
    context: Context,
    count: int,
    difficulty: str,
    topic: str | None = None,
) -> str:
    """Prompt for generating multiple-choice questions from retrieved context.

    The JSON shape is stated explicitly because the client requests JSON mode,
    which guarantees valid JSON but not the structure the application needs.
    """
    scope = f"about {topic}" if topic else "covering the material below"

    return f"""Write {count} multiple-choice questions {scope}, at {difficulty} difficulty.

Passages:
{context.render()}

Rules:
- Base every question only on the passages above.
- Give exactly four options; exactly one is correct.
- Make the three wrong options plausible but clearly incorrect to someone who
  understands the material.
- Do not write questions about the passages themselves ("According to passage
  2..."); ask about the subject matter.
- Do not repeat a question you have already written.
- The explanation must say why the correct option is right, in one or two
  sentences.
- `source` is the number of the passage the question comes from.

Return JSON in exactly this shape:
{{
  "questions": [
    {{
      "question": "...",
      "options": ["...", "...", "...", "..."],
      "correct_index": 0,
      "explanation": "...",
      "source": 1
    }}
  ]
}}"""
