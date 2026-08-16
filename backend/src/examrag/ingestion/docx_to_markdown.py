"""Convert DOCX content to Markdown.

Unlike PDF, DOCX carries real structure: paragraph styles name headings and
lists explicitly, so nothing has to be inferred from font metrics. DOCX has no
fixed pagination, so the result is a single unpaginated page.
"""

import io
import logging
import re

import docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from examrag.ingestion.document import DocumentLoadError, DocumentPage

logger = logging.getLogger(__name__)

_HEADING_STYLE = re.compile(r"^Heading (\d)$", re.IGNORECASE)
_MAX_HEADING_LEVEL = 6


def convert_docx_to_markdown(data: bytes) -> list[DocumentPage]:
    """Convert DOCX bytes into a single Markdown page.

    Raises:
        DocumentLoadError: the bytes are not a readable DOCX file.
    """
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises package and XML errors alike
        raise DocumentLoadError(f"Could not open the DOCX file: {exc}") from exc

    parts = [rendered for block in _iter_blocks(document) if (rendered := _render(block))]
    return [DocumentPage(markdown="\n\n".join(parts), number=None)]


def _iter_blocks(document: DocxDocument) -> list[Paragraph | Table]:
    """Yield paragraphs and tables in the order they appear in the document.

    python-docx exposes `paragraphs` and `tables` as separate collections, which
    loses their relative order; the underlying XML body preserves it.
    """
    body = document.element.body
    blocks: list[Paragraph | Table] = []
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            blocks.append(Table(child, document))
    return blocks


def _render(block: Paragraph | Table) -> str:
    return _render_table(block) if isinstance(block, Table) else _render_paragraph(block)


def _render_paragraph(paragraph: Paragraph) -> str:
    text = paragraph.text.strip()
    if not text:
        return ""

    style = (paragraph.style.name or "") if paragraph.style is not None else ""

    match = _HEADING_STYLE.match(style)
    if match:
        level = min(int(match.group(1)), _MAX_HEADING_LEVEL)
        return f"{'#' * level} {text}"
    if style.lower() == "title":
        return f"# {text}"
    if style.lower() == "subtitle":
        return f"## {text}"
    if style.startswith("List Number"):
        return f"1. {text}"
    if style.startswith("List"):  # List Bullet, List Paragraph, List Continue
        return f"- {text}"
    if style.lower() in {"quote", "intense quote"}:
        return f"> {text}"
    return text


def _render_table(table: Table) -> str:
    """Render a table in Markdown, treating the first row as the header."""
    rows = [[_cell_text(cell.text) for cell in row.cells] for row in table.rows]
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header, *body = padded

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _cell_text(text: str) -> str:
    """Flatten a cell to one line and escape the pipes that would break the table."""
    return " ".join(text.split()).replace("|", "\\|")
