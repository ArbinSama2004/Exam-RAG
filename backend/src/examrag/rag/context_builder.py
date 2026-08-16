"""Turn retrieved chunks into the context block a prompt can carry.

Every passage is numbered and labelled with its source, so the model can cite
`[1]` and the answer can be traced back to a file, page and section. A model
cannot ground an answer in a source it was never shown.
"""

import logging
from dataclasses import dataclass

from examrag.retrieval.base import RetrievedChunk

logger = logging.getLogger(__name__)

#: Ceiling on the assembled context. Roughly four characters per token, so this
#: is about 2k tokens of context — comfortable for small local models while
#: still holding several passages.
MAX_CONTEXT_CHARS = 8000


@dataclass(frozen=True, slots=True)
class ContextPassage:
    """One numbered passage, as the model sees it."""

    number: int
    text: str
    source: str
    chunk_id: str
    document_id: str


@dataclass(frozen=True, slots=True)
class Context:
    """The evidence assembled for one generation call."""

    passages: list[ContextPassage]

    @property
    def is_empty(self) -> bool:
        return not self.passages

    def render(self) -> str:
        """Render the context for a prompt."""
        return "\n\n".join(
            f"[{passage.number}] Source: {passage.source}\n{passage.text}"
            for passage in self.passages
        )


def build_context(chunks: list[RetrievedChunk], max_chars: int = MAX_CONTEXT_CHARS) -> Context:
    """Assemble retrieved chunks into a numbered, attributed context block.

    Chunks are taken in the order given — already best-first after reranking —
    and stop once the budget is reached, so the least relevant passage is the
    one dropped rather than an arbitrary one.
    """
    passages: list[ContextPassage] = []
    used = 0

    for chunk in chunks:
        # Account for the source line and separators, not just the text.
        cost = len(chunk.content) + len(chunk.source) + 20
        if passages and used + cost > max_chars:
            logger.debug("Context budget reached after %d passage(s)", len(passages))
            break
        passages.append(
            ContextPassage(
                number=len(passages) + 1,
                text=chunk.content,
                source=chunk.source,
                chunk_id=str(chunk.chunk_id),
                document_id=str(chunk.document_id),
            )
        )
        used += cost

    return Context(passages=passages)
