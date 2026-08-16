"""Load a supported document and return it as normalized Markdown.

This is the single entry point the ingestion pipeline uses. It decides which
format it is looking at and delegates the conversion; it does not implement any
conversion itself.
"""

import logging
from pathlib import Path

from examrag.enums import DocumentType
from examrag.ingestion.document import (
    DocumentLoadError,
    DocumentPage,
    LoadedDocument,
    UnsupportedDocumentTypeError,
)
from examrag.ingestion.docx_to_markdown import convert_docx_to_markdown
from examrag.ingestion.pdf_to_markdown import convert_pdf_to_markdown

logger = logging.getLogger(__name__)

EXTENSIONS: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
    ".txt": DocumentType.TXT,
}


def detect_document_type(filename: str) -> DocumentType:
    """Determine the document type from a filename.

    Raises:
        UnsupportedDocumentTypeError: the extension is not supported.
    """
    extension = Path(filename).suffix.lower()
    try:
        return EXTENSIONS[extension]
    except KeyError:
        supported = ", ".join(sorted(EXTENSIONS))
        raise UnsupportedDocumentTypeError(
            f"Unsupported file type '{extension or filename}'. Supported types: {supported}."
        ) from None


def load_document(filename: str, data: bytes) -> LoadedDocument:
    """Convert an uploaded file into normalized Markdown.

    Args:
        filename: Original filename, used to determine the format.
        data: Raw file bytes.

    Raises:
        UnsupportedDocumentTypeError: the extension is not supported.
        DocumentLoadError: the file is empty, corrupt or not decodable.
    """
    document_type = detect_document_type(filename)
    if not data:
        raise DocumentLoadError(f"'{filename}' is empty.")

    match document_type:
        case DocumentType.PDF:
            pages = convert_pdf_to_markdown(data)
        case DocumentType.DOCX:
            pages = convert_docx_to_markdown(data)
        case DocumentType.MARKDOWN | DocumentType.TXT:
            pages = _load_text(data)

    logger.info(
        "Loaded %s as %s: %d page(s), %d characters of Markdown",
        filename,
        document_type.value,
        len(pages),
        sum(len(page.markdown) for page in pages),
    )
    return LoadedDocument(filename=filename, document_type=document_type, pages=pages)


def _load_text(data: bytes) -> list[DocumentPage]:
    """Read Markdown or plain text.

    Markdown needs no conversion, and plain text is treated as Markdown whose
    paragraphs happen to carry no markup. Neither format is paginated.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Documents exported from older Windows tools are commonly cp1252.
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError("The file is not valid UTF-8 or CP-1252 text.") from exc

    # A UTF-8 BOM would otherwise become part of the first heading.
    return [DocumentPage(markdown=text.lstrip("﻿"), number=None)]
