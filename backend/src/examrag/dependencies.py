"""Shared FastAPI dependencies for the retrieval and generation stack.

The embedding model and the cross-encoder are expensive to load and safe to
share, so one of each is reused for the process rather than rebuilt per
request. Keeping them behind dependencies means tests override them instead of
loading a model.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from examrag.database.connection import get_session
from examrag.embeddings.embedding_generator import EmbeddingGenerator, get_shared_generator
from examrag.generation.llm_client import LLMClient, OllamaClient
from examrag.rag.pipeline import RagPipeline
from examrag.retrieval.reranker import CrossEncoderReranker


def get_embedding_generator() -> EmbeddingGenerator:
    """The process-wide embedding model, shared with ingestion."""
    return get_shared_generator()


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    """The process-wide cross-encoder. Loads on first use."""
    return CrossEncoderReranker()


def get_llm_client() -> LLMClient:
    """The configured LLM provider."""
    return OllamaClient()


def get_rag_pipeline(
    session: Annotated[AsyncSession, Depends(get_session)],
    generator: Annotated[EmbeddingGenerator, Depends(get_embedding_generator)],
    reranker: Annotated[CrossEncoderReranker, Depends(get_reranker)],
) -> RagPipeline:
    """A pipeline bound to the request's session, reusing the shared models."""
    return RagPipeline(session, generator, reranker)
