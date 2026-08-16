"""Tests for Reciprocal Rank Fusion."""

import uuid

from examrag.retrieval.base import RetrievedChunk
from examrag.retrieval.fusion import RRF_K, reciprocal_rank_fusion


def chunk(name: str, rank: int, score: float = 0.0) -> RetrievedChunk:
    """A chunk whose id is derived from `name`, so the same name is the same chunk."""
    return RetrievedChunk(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, name),
        document_id=uuid.uuid5(uuid.NAMESPACE_OID, "doc"),
        filename="notes.pdf",
        content=name,
        score=score,
        rank=rank,
    )


def contents(chunks: list[RetrievedChunk]) -> list[str]:
    return [item.content for item in chunks]


def test_a_chunk_found_by_both_strategies_outranks_one_found_by_either() -> None:
    """This is the signal hybrid retrieval exists to capture."""
    vector = [chunk("both", 2), chunk("vector-only", 1)]
    keyword = [chunk("both", 2), chunk("keyword-only", 1)]

    fused = reciprocal_rank_fusion([vector, keyword], top_k=3)

    assert contents(fused)[0] == "both"


def test_scores_are_the_sum_of_reciprocal_ranks() -> None:
    fused = reciprocal_rank_fusion([[chunk("a", 1)], [chunk("a", 3)]], top_k=1)

    assert fused[0].score == 1 / (RRF_K + 1) + 1 / (RRF_K + 3)


def test_ranks_are_renumbered_from_one() -> None:
    vector = [chunk("a", 1), chunk("b", 2), chunk("c", 3)]

    fused = reciprocal_rank_fusion([vector], top_k=3)

    assert [item.rank for item in fused] == [1, 2, 3]


def test_results_are_limited_to_top_k() -> None:
    vector = [chunk(str(index), index) for index in range(1, 11)]

    assert len(reciprocal_rank_fusion([vector], top_k=4)) == 4


def test_better_ranks_win() -> None:
    vector = [chunk("first", 1), chunk("second", 2), chunk("third", 3)]

    fused = reciprocal_rank_fusion([vector], top_k=3)

    assert contents(fused) == ["first", "second", "third"]


def test_a_single_top_result_cannot_dominate_a_consistent_one() -> None:
    """The damping constant is what stops one list's first place deciding everything."""
    vector = [chunk("spike", 1)]
    keyword = [chunk("steady", 2), chunk("spike", 30)]

    fused = reciprocal_rank_fusion([vector, keyword], top_k=2)

    # "spike" is first in one list and near-last in the other; "steady" is
    # solidly second in one. Ranks are close enough that spike still wins,
    # but the gap must be small rather than absolute.
    assert contents(fused)[0] == "spike"
    assert fused[0].score - fused[1].score < 1 / RRF_K


def test_metadata_survives_fusion() -> None:
    original = chunk("a", 1)

    fused = reciprocal_rank_fusion([[original]], top_k=1)[0]

    assert fused.chunk_id == original.chunk_id
    assert fused.filename == original.filename
    assert fused.content == original.content


def test_empty_lists_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion([[], []], top_k=5) == []


def test_no_lists_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion([], top_k=5) == []


def test_a_zero_or_negative_top_k_returns_nothing() -> None:
    assert reciprocal_rank_fusion([[chunk("a", 1)]], top_k=0) == []
    assert reciprocal_rank_fusion([[chunk("a", 1)]], top_k=-1) == []


def test_a_chunk_in_only_one_list_is_still_returned() -> None:
    fused = reciprocal_rank_fusion([[chunk("a", 1)], [chunk("b", 1)]], top_k=2)

    assert set(contents(fused)) == {"a", "b"}
