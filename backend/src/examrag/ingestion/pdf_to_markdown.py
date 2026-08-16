"""Convert PDF content to Markdown, one page at a time.

PDFs carry no structure — only positioned text with font metrics. Headings are
therefore inferred from font size relative to the document's body text, which
is what makes section-aware chunking and per-section MCQ generation possible
later. Text is extracted page by page so every chunk can be traced back to the
page it came from.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pymupdf

from examrag.ingestion.document import DocumentLoadError, DocumentPage

logger = logging.getLogger(__name__)

#: Bit set by PyMuPDF in a span's `flags` when the text is bold.
_BOLD_FLAG = 1 << 4

#: A line qualifies as a heading when its font is at least this much larger
#: than the document's body text. The thresholds are ordered largest first.
_HEADING_THRESHOLDS = ((1.55, 1), (1.30, 2), (1.12, 3))

#: Bold text no larger than the body font is only treated as a heading when the
#: line is short, so emphasised words inside a paragraph are not promoted.
_MAX_BOLD_HEADING_WORDS = 12

#: Glyphs a PDF may use to render a list item. The en and em dashes are
#: deliberate, hence the suppressed ambiguous-character warning.
_BULLET_CHARACTERS = "•●▪◦‣·-–—*"  # noqa: RUF001


@dataclass(frozen=True, slots=True)
class _Line:
    """A single visual line of text with the font metrics used to classify it."""

    text: str
    size: float
    bold: bool


def convert_pdf_to_markdown(data: bytes) -> list[DocumentPage]:
    """Convert PDF bytes into one Markdown page per PDF page.

    Raises:
        DocumentLoadError: the bytes are not a readable PDF.
    """
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf raises several unrelated exception types
        raise DocumentLoadError(f"Could not open the PDF: {exc}") from exc

    with document:
        pages = [_read_page(page) for page in document.pages()]
        body_size = _body_font_size(pages)
        return [
            DocumentPage(markdown=_render(lines, body_size), number=number)
            for number, lines in enumerate(pages, start=1)
        ]


def _read_page(page: pymupdf.Page) -> list[list[_Line]]:
    """Return the page's text blocks, each as a list of lines."""
    blocks: list[list[_Line]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0 is text; images and drawings are ignored
            continue
        lines = [line for line in map(_read_line, block["lines"]) if line is not None]
        if lines:
            blocks.append(lines)
    return blocks


def _read_line(raw_line: dict[str, Any]) -> _Line | None:
    """Collapse a line's spans into text plus its dominant font metrics."""
    spans = raw_line.get("spans", [])
    text = "".join(span["text"] for span in spans).strip()
    if not text:
        return None
    return _Line(
        text=text,
        size=max(span["size"] for span in spans),
        # Bold only counts when the whole line is bold; a bold word inside a
        # sentence should not turn the sentence into a heading.
        bold=all(span["flags"] & _BOLD_FLAG for span in spans),
    )


def _body_font_size(pages: list[list[list[_Line]]]) -> float:
    """Estimate the body font size as the most common size, weighted by length.

    Weighting by character count keeps a handful of large headings from
    outvoting the paragraphs that make up the bulk of the document.
    """
    weights: Counter[float] = Counter()
    for blocks in pages:
        for lines in blocks:
            for line in lines:
                weights[round(line.size, 1)] += len(line.text)
    if not weights:
        return 0.0
    return weights.most_common(1)[0][0]


def _heading_level(line: _Line, body_size: float) -> int | None:
    """Return the Markdown heading level for a line, or None if it is body text."""
    if body_size <= 0:
        return None

    ratio = line.size / body_size
    for threshold, level in _HEADING_THRESHOLDS:
        if ratio >= threshold:
            return level

    if line.bold and len(line.text.split()) <= _MAX_BOLD_HEADING_WORDS:
        return 3
    return None


def _render(blocks: list[list[_Line]], body_size: float) -> str:
    """Render one page's blocks as Markdown."""
    parts: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            parts.append(" ".join(paragraph))
            paragraph.clear()

    for lines in blocks:
        for line in lines:
            level = _heading_level(line, body_size)
            if level is not None:
                flush()
                parts.append(f"{'#' * level} {line.text}")
            elif _is_bullet(line.text):
                flush()
                parts.append(f"- {line.text.lstrip(_BULLET_CHARACTERS).strip()}")
            else:
                paragraph.append(line.text)
        flush()

    return "\n\n".join(parts)


def _is_bullet(text: str) -> bool:
    """Detect a list item that a PDF renders as a bullet glyph."""
    if len(text) < 2:
        return False
    return text[0] in _BULLET_CHARACTERS and text[1] in " \t"
