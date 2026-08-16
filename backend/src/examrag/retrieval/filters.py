"""The chunk-selection rules every retrieval strategy shares.

Vector and keyword search differ in how they rank, not in what they are allowed
to see. Keeping the selection rules here means a new strategy inherits them —
including the one that matters most: past papers are never returned as answer
evidence unless asked for explicitly.
"""

from sqlalchemy import ColumnElement, and_

from examrag.database.models import Chunk, Document
from examrag.enums import ProcessingStatus
from examrag.retrieval.base import RetrievalQuery


def chunk_filters(query: RetrievalQuery) -> ColumnElement[bool]:
    """Build the WHERE clause shared by every retrieval strategy."""
    conditions = [
        # A document mid-ingestion has partial chunks; returning them would
        # cite a source that is not finished.
        Document.status == ProcessingStatus.READY,
        Document.purpose == query.purpose,
    ]

    if query.document_ids:
        conditions.append(Chunk.document_id.in_(query.document_ids))

    if query.heading:
        conditions.append(Chunk.heading.ilike(f"%{query.heading}%"))

    return and_(*conditions)
