"""Past-paper FAQ generation.

No LLM involved: extraction is regex-based over chunks ingestion already
produced, and grouping reuses the same embedding model retrieval uses. That
makes this endpoint fast and deterministic, and the reason it recomputes on
every call instead of reading a stored result — there is nothing slow enough
to justify caching, and no risk of serving a result that predates a document
uploaded a minute ago.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.dependencies import get_embedding_generator
from examrag.embeddings.embedding_generator import EmbeddingError, EmbeddingGenerator
from examrag.faq.faq_pipeline import generate_faqs
from examrag.schemas.faq import (
    FaqClusterResponse,
    FaqGenerateRequest,
    FaqGenerateResponse,
    FaqSourceResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/faq", tags=["faq"])


@router.post("/generate", response_model=FaqGenerateResponse)
async def generate(
    request: FaqGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    generator: Annotated[EmbeddingGenerator, Depends(get_embedding_generator)],
) -> FaqGenerateResponse:
    """Extract, cluster and rank the questions found in the selected past papers."""
    try:
        result = await generate_faqs(
            session,
            generator,
            document_ids=request.document_ids or None,
            min_occurrences=request.min_occurrences,
        )
    except EmbeddingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return FaqGenerateResponse(
        question_count=result.question_count,
        document_count=result.document_count,
        clusters=[
            FaqClusterResponse(
                representative=cluster.representative,
                occurrence_count=cluster.occurrence_count,
                document_count=cluster.document_count,
                variants=cluster.variants,
                sources=[
                    FaqSourceResponse(
                        document_id=source.document_id,
                        filename=source.filename,
                        page_number=source.page_number,
                        heading=source.heading,
                    )
                    for source in cluster.sources
                ],
            )
            for cluster in result.clusters
        ],
    )
