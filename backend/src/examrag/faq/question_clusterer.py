"""Group semantically equivalent questions by cosine similarity.

No LLM and no new dependency: `EmbeddingGenerator` already produces
L2-normalized vectors for chunks, and clustering a paper's worth of questions
(tens to low hundreds) needs nothing more than a running centroid per cluster
compared with numpy, which embeddings already depend on. Adding scikit-learn
for this would repeat the mistake the project has avoided elsewhere — a
dependency arriving before anything actually needs it.
"""

from dataclasses import dataclass, field

import numpy as np

#: Cosine similarity above which two questions are treated as the same
#: question asked again. Picked from the labeled-set evaluation in
#: `tests/faq/test_clustering_evaluation.py`; see docs/decisions.md for the
#: precision/recall trade-off at this value.
DEFAULT_SIMILARITY_THRESHOLD = 0.83


@dataclass(slots=True)
class QuestionCluster:
    """One group of questions judged to be the same question."""

    member_indices: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.member_indices)


def cluster_questions(
    embeddings: list[list[float]],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[QuestionCluster]:
    """Assign each embedding's index to a cluster.

    A single greedy pass: each item joins whichever existing cluster its
    centroid is most similar to, if that similarity clears `threshold`,
    otherwise it starts a new cluster. The centroid is the running mean of a
    cluster's member vectors, re-normalized on every comparison — comparing
    against a growing cluster's *direction* is what makes this a similarity
    threshold rather than one that quietly loosens as a cluster grows.

    This is order-dependent, like any single-pass greedy clustering: it will
    occasionally split into two clusters what a global method would merge into
    one. That trade-off is what keeps this dependency-free and fast enough to
    run on every request rather than needing to be a background job.
    """
    if not embeddings:
        return []

    vectors = np.asarray(embeddings, dtype=np.float64)
    clusters: list[QuestionCluster] = []
    sums = np.zeros((0, vectors.shape[1]), dtype=np.float64)

    for index, vector in enumerate(vectors):
        best_cluster, best_similarity = -1, -1.0
        if clusters:
            sizes = np.array([[cluster.size] for cluster in clusters])
            centroids = sums / sizes
            norms = np.linalg.norm(centroids, axis=1)
            norms[norms == 0] = 1.0
            # `vector` is already unit-length, so dividing by the centroid's
            # norm alone yields the cosine similarity between them.
            similarities = (centroids @ vector) / norms
            best_cluster = int(np.argmax(similarities))
            best_similarity = float(similarities[best_cluster])

        if best_cluster >= 0 and best_similarity >= threshold:
            clusters[best_cluster].member_indices.append(index)
            sums[best_cluster] += vector
        else:
            clusters.append(QuestionCluster(member_indices=[index]))
            sums = np.vstack([sums, vector])

    return clusters
