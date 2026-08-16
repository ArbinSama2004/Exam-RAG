"""Split normalized Markdown into the chunks that get embedded and retrieved.

Chunking is structure-aware rather than a fixed character window: headings
start a new chunk and are recorded as a breadcrumb on every chunk beneath them.
That heading path is what lets a retrieved chunk say where it came from, and
what Phase 2 uses to spread "all topics" MCQ generation across a document's
sections instead of over one global context.

Chunks carry a small overlap so a sentence split across a boundary still has
its neighbours nearby in at least one chunk.
"""

import logging
import re
from dataclasses import dataclass

from examrag.ingestion.document import DocumentPage, LoadedDocument

logger = logging.getLogger(__name__)

#: Identifies the chunking strategy that produced a stored chunk. Bump this
#: whenever the algorithm or any constant below changes, so documents chunked
#: by an older version are detectable and can be re-ingested.
CHUNKER_VERSION = "markdown-v1"

#: Size a chunk aims for. Large enough to hold a coherent explanation, small
#: enough that retrieval returns a focused passage rather than a whole section.
TARGET_CHUNK_CHARS = 1200

#: A chunk is never emitted longer than this; oversized blocks are split.
MAX_CHUNK_CHARS = 1600

#: Chunks shorter than this are merged into their neighbour where possible, so
#: a stray line does not become its own barely-meaningful embedding.
MIN_CHUNK_CHARS = 200

#: How much of the previous chunk is repeated at the start of the next.
OVERLAP_CHARS = 150

#: Longest heading breadcrumb stored, matching `chunks.heading` in the schema.
MAX_HEADING_CHARS = 512

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_HEADING_SEPARATOR = " > "


@dataclass(frozen=True, slots=True)
class TextChunk:
    """One retrievable passage, with the metadata that makes it traceable."""

    index: int
    content: str
    page_number: int | None = None
    heading: str | None = None

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass(slots=True)
class _Block:
    """A paragraph, list item or heading, tagged with where it came from."""

    text: str
    page_number: int | None
    heading: str | None
    is_heading: bool


def chunk_document(document: LoadedDocument) -> list[TextChunk]:
    """Split a cleaned document into chunks, in reading order."""
    chunks = _assemble(_blocks(document.pages))
    logger.info(
        "Chunked %s into %d chunk(s) using %s",
        document.filename,
        len(chunks),
        CHUNKER_VERSION,
    )
    return chunks


def _blocks(pages: list[DocumentPage]) -> list[_Block]:
    """Flatten pages into blocks, tracking the heading path as it changes."""
    blocks: list[_Block] = []
    path: list[str] = []

    for page in pages:
        for raw in page.markdown.split("\n\n"):
            text = raw.strip()
            if not text:
                continue

            heading_match = _HEADING.match(text)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                # Drop any deeper headings still on the path, then record this
                # one at its own level.
                del path[level - 1 :]
                path.append(title)
                blocks.append(
                    _Block(
                        text=text,
                        page_number=page.number,
                        heading=_breadcrumb(path),
                        is_heading=True,
                    )
                )
            else:
                blocks.append(
                    _Block(
                        text=text,
                        page_number=page.number,
                        heading=_breadcrumb(path),
                        is_heading=False,
                    )
                )
    return blocks


def _breadcrumb(path: list[str]) -> str | None:
    """Render the heading path, truncated to what the schema stores."""
    if not path:
        return None
    return _HEADING_SEPARATOR.join(path)[:MAX_HEADING_CHARS]


def _assemble(blocks: list[_Block]) -> list[TextChunk]:
    """Group blocks into chunks, starting a new one at every heading."""
    chunks: list[TextChunk] = []
    buffer: list[str] = []
    start: _Block | None = None
    has_body = False

    def flush() -> None:
        nonlocal buffer, start, has_body
        if not buffer or start is None:
            return
        content = "\n\n".join(buffer).strip()
        if content:
            _append(chunks, content, start)
        buffer = []
        start = None
        has_body = False

    for block in blocks:
        if block.is_heading:
            # A heading opens a new section, so whatever came before is
            # complete — unless nothing but headings has accumulated. A
            # heading immediately followed by a subheading would otherwise
            # become a chunk with a title and no content.
            if has_body:
                flush()
            start = block

        for piece in _split_oversized(block.text):
            if start is None:
                start = block
            candidate = len(_joined(buffer)) + len(piece)
            if buffer and candidate > TARGET_CHUNK_CHARS:
                tail = _overlap(buffer)
                flush()
                start = block
                buffer = [tail] if tail else []
            buffer.append(piece)

        has_body = has_body or not block.is_heading

    flush()
    return _merge_short(chunks)


def _joined(buffer: list[str]) -> str:
    return "\n\n".join(buffer)


def _append(chunks: list[TextChunk], content: str, start: _Block) -> None:
    chunks.append(
        TextChunk(
            index=len(chunks),
            content=content,
            page_number=start.page_number,
            heading=start.heading,
        )
    )


def _split_oversized(text: str) -> list[str]:
    """Break a block that alone exceeds the maximum into sentence-sized pieces."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_BOUNDARY.split(text):
        if current and len(current) + len(sentence) + 1 > TARGET_CHUNK_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)

    # Prose without sentence punctuation (a long table row, say) still has to
    # be cut somewhere.
    return [part for piece in pieces for part in _hard_split(piece)]


def _hard_split(text: str) -> list[str]:
    """Cut at the target size, not the maximum.

    A piece is emitted with the previous chunk's overlap prepended, so cutting
    at MAX_CHUNK_CHARS here would produce a chunk longer than the maximum.
    """
    if len(text) <= TARGET_CHUNK_CHARS:
        return [text]
    return [
        text[index : index + TARGET_CHUNK_CHARS]
        for index in range(0, len(text), TARGET_CHUNK_CHARS)
    ]


def _overlap(buffer: list[str]) -> str:
    """Return the tail of the current chunk to repeat at the start of the next.

    The cut is made on a sentence boundary where one is available, so the
    overlap reads as text rather than as a fragment.
    """
    text = _joined(buffer)
    if len(text) <= OVERLAP_CHARS:
        return text

    tail = text[-OVERLAP_CHARS:]
    sentences = _SENTENCE_BOUNDARY.split(tail)
    return tail if len(sentences) == 1 else " ".join(sentences[1:]).strip()


def _merge_short(chunks: list[TextChunk]) -> list[TextChunk]:
    """Fold a too-short chunk into its predecessor when they fit together.

    Only chunks under the same heading are merged: combining across a section
    boundary would file the text under the wrong heading and break attribution.
    """
    merged: list[TextChunk] = []
    for chunk in chunks:
        previous = merged[-1] if merged else None
        fits = (
            previous is not None
            and previous.heading == chunk.heading
            and chunk.char_count < MIN_CHUNK_CHARS
            and previous.char_count + chunk.char_count <= MAX_CHUNK_CHARS
        )
        if fits and previous is not None:
            merged[-1] = TextChunk(
                index=previous.index,
                content=f"{previous.content}\n\n{chunk.content}",
                page_number=previous.page_number,
                heading=previous.heading,
            )
        else:
            merged.append(
                TextChunk(
                    index=len(merged),
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                )
            )
    return merged
