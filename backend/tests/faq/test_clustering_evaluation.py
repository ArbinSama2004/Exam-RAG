"""Evaluate clustering quality against a hand-labeled set of exam questions.

This is Phase 3's evaluation: a small corpus of realistic past-paper
questions, each assigned to a true group by hand — several phrasings of the
same question, and distractors that must never merge with anything. The real
embedding model turns each into a vector, `cluster_questions` groups them at
`DEFAULT_SIMILARITY_THRESHOLD`, and the result is scored against the hand
labels with pairwise precision/recall/F1: for every pair of questions, did
clustering agree with the label on whether they are the same question?

This needs the real model — a fake or hash-based encoder cannot tell a
paraphrase from a distractor — so it is opt-in, like the embedding suite's own
real-model test.
"""

import itertools
import os

import pytest

from examrag.embeddings.embedding_generator import EmbeddingGenerator
from examrag.faq.question_clusterer import DEFAULT_SIMILARITY_THRESHOLD, cluster_questions
from examrag.faq.question_normalizer import normalize_question

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAMRAG_TEST_REAL_MODEL") != "1",
    reason="Downloads/loads the real model; set EXAMRAG_TEST_REAL_MODEL=1 to run.",
)

#: (question text, true group label). Four groups of repeated questions in the
#: style of real past papers, plus five one-off distractors that must never be
#: merged with anything.
_LABELED_QUESTIONS: list[tuple[str, str]] = [
    # Group: OSI model
    ("Explain the seven layers of the OSI model with a diagram. [10 marks]", "osi"),
    (
        "Describe the seven layers of the OSI reference model, illustrating each with a diagram.",
        "osi",
    ),
    ("With the aid of a diagram, explain the seven layers of the OSI model. (10 points)", "osi"),
    # Group: TCP vs UDP
    ("Differentiate between TCP and UDP protocols. [8 marks]", "tcp_udp"),
    ("Compare and contrast TCP and UDP.", "tcp_udp"),
    ("What are the key differences between TCP and UDP?", "tcp_udp"),
    # Group: subnetting
    (
        "Given the IP address 192.168.1.0/24, calculate the number of usable hosts. [6 marks]",
        "subnetting",
    ),
    (
        "For the network 192.168.1.0/24, determine how many usable host addresses are available.",
        "subnetting",
    ),
    # Group: DNS
    ("Explain how DNS resolves a domain name to an IP address.", "dns"),
    (
        "Describe the process by which DNS translates a hostname into an IP address. [5 marks]",
        "dns",
    ),
    # Distractors: each its own group, sharing no true match with anything else.
    ("Define photosynthesis and explain its two main stages.", "distractor_biology"),
    ("Discuss the causes of the French Revolution.", "distractor_history"),
    ("Solve for x: 2x + 5 = 17.", "distractor_algebra"),
    ("Explain Newton's second law of motion with an example.", "distractor_physics"),
    ("What is the time complexity of binary search?", "distractor_algorithms"),
]

#: The clustering evaluation must clear this pairwise F1 before the default
#: threshold is trusted. See docs/decisions.md for the trade-off recorded at
#: DEFAULT_SIMILARITY_THRESHOLD.
_MINIMUM_F1 = 0.75


def test_clustering_quality_on_a_labeled_question_set() -> None:
    texts = [normalize_question(text) for text, _ in _LABELED_QUESTIONS]
    true_labels = [label for _, label in _LABELED_QUESTIONS]

    embeddings = EmbeddingGenerator().embed_texts(texts)
    clusters = cluster_questions(embeddings, threshold=DEFAULT_SIMILARITY_THRESHOLD)

    predicted_labels = [None] * len(texts)
    for cluster_index, cluster in enumerate(clusters):
        for member_index in cluster.member_indices:
            predicted_labels[member_index] = cluster_index

    precision, recall, f1 = _pairwise_scores(true_labels, predicted_labels)
    print(  # the whole point of this test is a human-readable evaluation report
        f"\nFAQ clustering evaluation @ threshold={DEFAULT_SIMILARITY_THRESHOLD}: "
        f"precision={precision:.2f} recall={recall:.2f} f1={f1:.2f} "
        f"over {len(texts)} questions in {len(clusters)} predicted cluster(s) "
        f"(labeled into {len(set(true_labels))} true group(s))"
    )

    assert f1 >= _MINIMUM_F1, (
        f"Clustering F1 {f1:.2f} fell below {_MINIMUM_F1} at threshold "
        f"{DEFAULT_SIMILARITY_THRESHOLD}; the labeled set or the threshold needs revisiting."
    )


def _pairwise_scores(
    true_labels: list[str], predicted_labels: list[int | None]
) -> tuple[float, float, float]:
    """Precision/recall/F1 over every pair: did clustering agree with the label?"""
    true_positive = false_positive = false_negative = 0

    for i, j in itertools.combinations(range(len(true_labels)), 2):
        same_true = true_labels[i] == true_labels[j]
        same_predicted = predicted_labels[i] == predicted_labels[j]
        if same_predicted and same_true:
            true_positive += 1
        elif same_predicted and not same_true:
            false_positive += 1
        elif not same_predicted and same_true:
            false_negative += 1

    precision = (
        true_positive / (true_positive + false_positive) if true_positive or false_positive else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive or false_negative else 1.0
    )
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1
