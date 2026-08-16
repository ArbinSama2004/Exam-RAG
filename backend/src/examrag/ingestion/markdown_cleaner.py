"""Clean normalized Markdown before it is chunked.

Conversion from PDF in particular leaves artefacts that would otherwise end up
inside chunks and be embedded as if they were content: words hyphenated across
line breaks, page numbers, and the running header or footer repeated on every
page. Removing them here means every later stage — chunking, embedding,
retrieval — works on text that reads the way the author wrote it.

Fenced code blocks are passed through untouched, since whitespace is
significant inside them.
"""

import logging
import re
import unicodedata
from collections import Counter

from examrag.ingestion.document import DocumentPage, LoadedDocument

logger = logging.getLogger(__name__)

#: A line that is only a page marker: "7", "Page 7", "7 / 30", "Page 7 of 30".
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page\s+)?\d+\s*(?:(?:/|of)\s*\d+)?\s*$",
    re.IGNORECASE,
)

#: A word split across a line break by PDF justification: "net-\nwork". The
#: gap may include a blank line, because PDF extraction often puts the two
#: halves in separate text blocks. Both halves must be lowercase, so a line
#: legitimately ending in a dash before a new sentence or list item is left
#: alone.
_HYPHENATED_LINE_BREAK = re.compile(r"([a-z])-\n\s*([a-z])")

_CODE_FENCE = re.compile(r"(```.*?```|~~~.*?~~~)", re.DOTALL)

#: Lines whose own line break carries meaning: headings, list items, table
#: rows and block quotes. Everything else is prose that can be reflowed.
_STRUCTURAL_LINE = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\|)")

#: Lines considered when looking for a running header or footer.
_EDGE_LINES = 2

#: A line must appear on at least this share of pages to count as a running
#: header or footer rather than as content that happens to repeat.
_REPEAT_RATIO = 0.6

#: Below this many pages there is not enough evidence to call a line a header.
_MIN_PAGES_FOR_REPEAT_DETECTION = 3


def clean_document(document: LoadedDocument) -> LoadedDocument:
    """Clean every page, removing artefacts that only pagination can reveal.

    Running headers and footers can only be identified by comparing pages, so
    they are handled here rather than in `clean_markdown`.
    """
    repeated = _find_repeated_edge_lines(document.pages)
    if repeated:
        logger.debug("Removing %d repeated header/footer line(s)", len(repeated))

    pages = [
        DocumentPage(
            markdown=clean_markdown(page.markdown, drop_lines=repeated), number=page.number
        )
        for page in document.pages
    ]
    return LoadedDocument(
        filename=document.filename,
        document_type=document.document_type,
        pages=pages,
    )


def clean_markdown(text: str, drop_lines: frozenset[str] = frozenset()) -> str:
    """Normalize one piece of Markdown.

    Args:
        text: The Markdown to clean.
        drop_lines: Normalized lines to remove wherever they appear, used for
            running headers and footers found across pages.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Code fences are preserved verbatim, so cleaning runs on the prose between
    # them. re.split keeps the captured fences in the result.
    parts = _CODE_FENCE.split(text)
    cleaned = [
        part if index % 2 else _clean_prose(part, drop_lines) for index, part in enumerate(parts)
    ]
    return _collapse_blank_lines("".join(cleaned)).strip()


def _clean_prose(text: str, drop_lines: frozenset[str]) -> str:
    text = _HYPHENATED_LINE_BREAK.sub(r"\1\2", text)
    text = _strip_control_characters(text)

    kept = [
        cleaned_line
        for line in text.split("\n")
        if (cleaned_line := _clean_line(line)) is not None
        and _normalize(cleaned_line) not in drop_lines
    ]
    return _reflow(kept)


def _reflow(lines: list[str]) -> str:
    """Rejoin prose that a PDF wrapped mid-sentence.

    A converted PDF breaks a paragraph wherever the page did. Left alone, those
    breaks travel into chunks and into the context shown to the user. Lines
    whose break is meaningful — headings, list items, table rows, quotes — are
    left exactly as they are.
    """
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for line in lines:
        if not line.strip():
            flush()
            out.append("")
        elif _STRUCTURAL_LINE.match(line):
            flush()
            out.append(line)
        else:
            paragraph.append(line.strip())
    flush()
    return "\n".join(out)


def _clean_line(line: str) -> str | None:
    """Normalize one line, or return None if it should be dropped."""
    # Leading whitespace is meaningful in Markdown lists, so only runs inside
    # the line are collapsed.
    indent = line[: len(line) - len(line.lstrip(" \t"))]
    body = re.sub(r"[ \t]{2,}", " ", line.strip())

    if _PAGE_NUMBER_LINE.match(body):
        return None
    return f"{indent}{body}" if body else ""


def _strip_control_characters(text: str) -> str:
    """Drop control characters and normalize exotic spaces to plain spaces."""
    return "".join(
        " " if unicodedata.category(char) == "Zs" else char
        for char in text
        if char == "\n" or unicodedata.category(char) != "Cc"
    )


def _collapse_blank_lines(text: str) -> str:
    """Reduce runs of blank lines to a single blank line."""
    return re.sub(r"\n{3,}", "\n\n", text)


def _find_repeated_edge_lines(pages: list[DocumentPage]) -> frozenset[str]:
    """Find lines that repeat at the top or bottom of most pages.

    Only the first and last lines of each page are considered: a sentence that
    genuinely recurs mid-page is content, while the same line pinned to the
    edge of most pages is a running header or footer.
    """
    if len(pages) < _MIN_PAGES_FOR_REPEAT_DETECTION:
        return frozenset()

    counts: Counter[str] = Counter()
    for page in pages:
        lines = [line for line in page.markdown.split("\n") if line.strip()]
        # Never let the head and tail slices meet: on a short page that would
        # count mid-page content as an edge line and delete it as a header.
        edge_count = min(_EDGE_LINES, len(lines) // 2)
        if not edge_count:
            continue
        edges = lines[:edge_count] + lines[len(lines) - edge_count :]
        # A header appearing twice on one page still counts once.
        counts.update({_normalize(line) for line in edges if _normalize(line)})

    threshold = max(_MIN_PAGES_FOR_REPEAT_DETECTION, int(len(pages) * _REPEAT_RATIO))
    return frozenset(line for line, count in counts.items() if count >= threshold)


def _normalize(line: str) -> str:
    """Casefolded, whitespace-collapsed form used to compare lines across pages."""
    return " ".join(line.split()).casefold()
