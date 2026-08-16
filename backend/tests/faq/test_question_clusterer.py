"""Tests for greedy cosine clustering over pre-computed vectors.

Vectors here are small and hand-picked rather than real embeddings, so the
clustering *algorithm* is what is under test. Whether real questions actually
land above or below the threshold is a separate question, answered by the
opt-in evaluation in test_clustering_evaluation.py.
"""

from examrag.faq.question_clusterer import cluster_questions


def test_no_embeddings_yields_no_clusters() -> None:
    assert cluster_questions([]) == []


def test_a_single_embedding_forms_its_own_cluster() -> None:
    clusters = cluster_questions([[1.0, 0.0]])

    assert len(clusters) == 1
    assert clusters[0].member_indices == [0]


def test_identical_vectors_join_one_cluster() -> None:
    clusters = cluster_questions([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], threshold=0.9)

    assert len(clusters) == 1
    assert sorted(clusters[0].member_indices) == [0, 1, 2]


def test_orthogonal_vectors_form_separate_clusters() -> None:
    clusters = cluster_questions([[1.0, 0.0], [0.0, 1.0]], threshold=0.5)

    assert len(clusters) == 2
    assert {tuple(c.member_indices) for c in clusters} == {(0,), (1,)}


def test_similarity_at_or_above_threshold_joins() -> None:
    # cos(a, b) = 0.6 for unit vectors [1, 0] and [0.6, 0.8].
    clusters = cluster_questions([[1.0, 0.0], [0.6, 0.8]], threshold=0.6)

    assert len(clusters) == 1


def test_similarity_below_threshold_splits() -> None:
    clusters = cluster_questions([[1.0, 0.0], [0.6, 0.8]], threshold=0.7)

    assert len(clusters) == 2


def test_a_third_vector_joins_the_nearer_of_two_clusters() -> None:
    # Cluster 0 centres on [1, 0]; cluster 1 centres on [0, 1]. The third
    # vector is closer to cluster 0.
    clusters = cluster_questions(
        [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]],
        threshold=0.5,
    )

    assert len(clusters) == 2
    joined = next(c for c in clusters if 0 in c.member_indices)
    assert 2 in joined.member_indices


def test_indices_preserve_input_order_within_a_cluster() -> None:
    clusters = cluster_questions([[1.0, 0.0], [1.0, 0.0]], threshold=0.9)

    assert clusters[0].member_indices == [0, 1]
