"""Pull individual questions out of a past paper's already-stored chunks.

Past papers get no special treatment during ingestion — they go through the
same PDF/DOCX/MD/TXT to Markdown pipeline as study material. What sets a
question apart on the page is its numbering ("1.", "Q2", "(a)", "b)"), and
`markdown_cleaner`'s `_STRUCTURAL_LINE` rule already keeps a numbered line's
break intact rather than reflowing it into the paragraph around it — the same
rule that protects list items. That is what makes a line-based heuristic here
reliable enough to use: a marker line starts a question, and every line after
it belongs to that question until the next marker or a blank line.

This is a heuristic, not a parser: an unusually formatted paper can produce a
missed or malformed question, the same trade-off `pdf_to_markdown`'s heading
inference makes. Downstream, a bad extraction degrades one entry in the FAQ
list rather than breaking anything.
"""

import re
import uuid
from dataclasses import dataclass

#: A question's opening marker: "Q1", "Question 2:", "3.", "12)", "(a)", "b)".
#: Matched only at the start of a line, mirroring how the cleaner decides a
#: line's break is structural.
_MARKER = re.compile(
    r"""^\s*
    (?:
        Q(?:uestion)?\.?\s*\d{1,3}\s*[.:)]?    # Q1  Question 2:  Q3)
        |
        \d{1,3}\s*[.)]                          # 1.  12)
        |
        \(\s*[a-zA-Z0-9]{1,3}\s*\)               # (a)  (iv)  (1)
        |
        [a-zA-Z]\)                               # a)
    )
    \s+
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Below this many characters, a marker line is treated as a stray label
#: ("1. Section A") rather than a question, and dropped.
MIN_QUESTION_CHARS = 12


@dataclass(frozen=True, slots=True)
class SourceChunk:
    """The slice of a stored chunk that extraction needs.

    A plain dataclass rather than the ORM `Chunk` so this module — and its
    tests — do not depend on a database session.
    """

    document_id: uuid.UUID
    filename: str
    content: str
    page_number: int | None
    heading: str | None


@dataclass(frozen=True, slots=True)
class ExtractedQuestion:
    """One question found in one chunk, with where it came from."""

    document_id: uuid.UUID
    filename: str
    page_number: int | None
    heading: str | None
    text: str


def extract_questions(chunks: list[SourceChunk]) -> list[ExtractedQuestion]:
    """Extract every question found across the given chunks, in order."""
    questions: list[ExtractedQuestion] = []
    for chunk in chunks:
        # Chunk content is blocks joined by blank lines (see chunker._assemble);
        # a question never spans two blocks, since a block boundary is either a
        # heading or wherever the chunker itself cut the text.
        for block in chunk.content.split("\n\n"):
            questions.extend(_extract_block(block, chunk))
    return questions


def _extract_block(block: str, chunk: SourceChunk) -> list[ExtractedQuestion]:
    lines = [line for line in block.split("\n") if line.strip()]
    items: list[ExtractedQuestion] = []
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        text = re.sub(r"\s{2,}", " ", " ".join(current)).strip()
        if len(text) >= MIN_QUESTION_CHARS:
            items.append(
                ExtractedQuestion(
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                    text=text,
                )
            )
        current = None

    for line in lines:
        match = _MARKER.match(line)
        if match:
            flush()
            current = [line[match.end() :].strip()]
        elif current is not None:
            # A continuation line of the question currently being built.
            current.append(line.strip())
        # Lines before the block's first marker (a stray heading fragment, an
        # instruction line) belong to no question and are dropped.

    flush()
    return items
