"""Combine result lists with Reciprocal Rank Fusion.

Vector similarity and text-search relevance are different scales — a cosine
score of 0.7 and a `ts_rank_cd` of 0.09 say nothing about each other. RRF
sidesteps the problem by combining *ranks* rather than scores: each list votes
for a chunk with weight `1 / (k + rank)`, and the votes are summed.

A chunk found by both strategies therefore outranks one found by only one,
which is exactly the signal hybrid retrieval exists to capture.
"""

import logging
from collections import defaultdict
from dataclasses import replace

from examrag.retrieval.base import RetrievedChunk

logger = logging.getLogger(__name__)

#: Dampens the influence of the very top ranks, so one list cannot dominate on
#: the strength of a single first-place result. 60 is the value from the
#: original RRF paper and the common default.
RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievedChunk]],
    top_k: int,
    k: int = RRF_K,
) -> list[RetrievedChunk]:
    """Fuse ranked result lists into one.

    Args:
        result_lists: One ranked list per strategy, best first.
        top_k: How many fused results to return.
        k: The RRF damping constant.

    Returns:
        Fused chunks, best first, with `score` set to the RRF score and `rank`
        renumbered from 1.
    """
    if top_k <= 0:
        return []

    scores: dict[str, float] = defaultdict(float)
    chunks: dict[str, RetrievedChunk] = {}

    for results in result_lists:
        for chunk in results:
            key = str(chunk.chunk_id)
            scores[key] += 1.0 / (k + chunk.rank)
            # Keep the first copy seen; the text and metadata are identical
            # whichever strategy found it.
            chunks.setdefault(key, chunk)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    fused = [
        replace(chunks[key], score=score, rank=index)
        for index, (key, score) in enumerate(ordered, start=1)
    ]

    logger.debug(
        "Fused %d list(s) into %d result(s)",
        len(result_lists),
        len(fused),
    )
    return fused
