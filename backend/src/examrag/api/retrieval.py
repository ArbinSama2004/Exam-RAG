"""Retrieval comparison and grounded answers.

`POST /retrieval/compare` exists so the differences between retrieval methods
are visible rather than asserted. It reuses the same vector retriever, keyword
retriever, fusion and reranker as the main pipeline — a separate
comparison-only implementation could drift and would prove nothing about the
system in use.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from examrag.dependencies import get_llm_client, get_rag_pipeline
from examrag.generation.answer_generator import AnswerGenerator
from examrag.generation.llm_client import LLMClient, LLMError
from examrag.rag.pipeline import RagPipeline
from examrag.retrieval.base import RetrievalQuery, RetrievedChunk
from examrag.retrieval.reranker import RerankerError
from examrag.schemas.retrieval import (
    AnswerPassage,
    AnswerResponse,
    RetrievalComparison,
    RetrievalRequest,
    RetrievedChunkResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/compare", response_model=RetrievalComparison)
async def compare_retrieval(
    request: RetrievalRequest,
    pipeline: Annotated[RagPipeline, Depends(get_rag_pipeline)],
) -> RetrievalComparison:
    """Run one query through every retrieval method and return all four results.

    Vector-only and keyword-only show what each half contributes; hybrid shows
    what fusion does with them; hybrid-plus-reranking shows what actually
    reaches the model.
    """
    query = _to_query(request)
    try:
        trace = await pipeline.retrieve(query)
    except RerankerError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return RetrievalComparison(
        query=request.query,
        vector=_serialize(trace.vector),
        keyword=_serialize(trace.keyword),
        hybrid=_serialize(trace.fused),
        hybrid_reranked=_serialize(trace.reranked),
    )


@router.post("/answer", response_model=AnswerResponse)
async def answer_question(
    request: RetrievalRequest,
    pipeline: Annotated[RagPipeline, Depends(get_rag_pipeline)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> AnswerResponse:
    """Answer a question from the uploaded study material."""
    generator = AnswerGenerator(pipeline, llm)
    try:
        result = await generator.answer(request.query, frozenset(request.document_ids))
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except RerankerError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return AnswerResponse(
        question=result.question,
        answer=result.answer,
        passages=[
            AnswerPassage(
                number=passage.number,
                text=passage.text,
                source=passage.source,
                chunk_id=passage.chunk_id,
                document_id=passage.document_id,
            )
            for passage in result.passages
        ],
        model=result.model,
        is_grounded=result.is_grounded,
    )


def _to_query(request: RetrievalRequest) -> RetrievalQuery:
    return RetrievalQuery(
        text=request.query,
        purpose=request.purpose,
        document_ids=frozenset(request.document_ids),
    )


def _serialize(chunks: list[RetrievedChunk]) -> list[RetrievedChunkResponse]:
    return [
        RetrievedChunkResponse(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            filename=chunk.filename,
            content=chunk.content,
            score=chunk.score,
            rank=chunk.rank,
            page_number=chunk.page_number,
            heading=chunk.heading,
            source=chunk.source,
        )
        for chunk in chunks
    ]
