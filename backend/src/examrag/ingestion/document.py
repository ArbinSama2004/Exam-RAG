"""The normalized document representation, plus the errors loading can raise.

Every supported format is converted into the same shape: an ordered list of
pages, each holding Markdown. Page numbers are preserved here rather than
recovered later, because they are the only point at which the source layout is
still known — chunking and retrieval depend on them for source attribution.
"""

from dataclasses import dataclass, field

from examrag.enums import DocumentType


class DocumentLoadError(Exception):
    """A document could not be read or converted."""


class UnsupportedDocumentTypeError(DocumentLoadError):
    """The file extension is not one of PDF, DOCX, Markdown or TXT."""


@dataclass(frozen=True, slots=True)
class DocumentPage:
    """One page of normalized Markdown.

    Formats without pagination (DOCX, Markdown, TXT) produce a single page with
    `number = None`, so downstream code never has to invent a page number.
    """

    markdown: str
    number: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.markdown.strip()


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """A source file after conversion to Markdown."""

    filename: str
    document_type: DocumentType
    pages: list[DocumentPage] = field(default_factory=list)

    @property
    def markdown(self) -> str:
        """The whole document as one Markdown string."""
        return "\n\n".join(page.markdown for page in self.pages if not page.is_empty)

    @property
    def page_count(self) -> int:
        return len(self.pages)
