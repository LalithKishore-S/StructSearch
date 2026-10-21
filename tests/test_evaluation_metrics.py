import math
import random

import pytest

from structsearch.evaluation import (
    METRICS,
    evaluate_ranking,
    mean_metrics,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

# ranking a..e, relevant b and d (plus z, which is never retrieved)
RANKING = ["a", "b", "c", "d", "e"]
REL = {"b": 1, "d": 1, "z": 1, "a": 0}


def test_precision_at_k():
    assert precision_at_k(RANKING, REL, 5) == pytest.approx(2 / 5)
    assert precision_at_k(RANKING, REL, 2) == pytest.approx(1 / 2)
    assert precision_at_k(RANKING, REL, 1) == 0.0


def test_precision_divides_by_k_even_when_fewer_results():
    assert precision_at_k(["b"], REL, 4) == pytest.approx(1 / 4)


def test_recall_at_k():
    assert recall_at_k(RANKING, REL, 5) == pytest.approx(2 / 3)
    assert recall_at_k(RANKING, REL, 2) == pytest.approx(1 / 3)


def test_recall_without_relevant_units_is_zero():
    assert recall_at_k(RANKING, {"a": 0}, 5) == 0.0
    assert recall_at_k([], {}, 5) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank(RANKING, REL, 5) == pytest.approx(1 / 2)
    assert reciprocal_rank(["b", "a"], REL, 2) == 1.0
    assert reciprocal_rank(["a", "c", "d"], REL, 3) == pytest.approx(1 / 3)


def test_reciprocal_rank_only_looks_inside_top_k():
    assert reciprocal_rank(["a", "b", "c"], {"c": 1}, 2) == 0.0
    assert reciprocal_rank([], REL, 3) == 0.0


def test_ndcg_binary_hand_computed():
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    ideal = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)  # three relevant units, top 5
    assert ndcg_at_k(RANKING, REL, 5) == pytest.approx(dcg / ideal)
    assert ndcg_at_k(RANKING, REL, 5) == pytest.approx(0.4982, abs=1e-4)


def test_ndcg_perfect_and_empty():
    assert ndcg_at_k(["b", "d", "z"], REL, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["a", "c"], REL, 2) == 0.0
    assert ndcg_at_k([], {}, 3) == 0.0


def test_ndcg_graded_prefers_higher_grade_first():
    rel = {"a": 1, "b": 3}
    worse = ndcg_at_k(["a", "b"], rel, 2)
    better = ndcg_at_k(["b", "a"], rel, 2)
    assert better == pytest.approx(1.0)
    assert worse == pytest.approx((1 + 7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert worse < better


def test_unlabelled_and_negative_grades_count_as_not_relevant():
    assert precision_at_k(["x", "y"], {"y": -2}, 2) == 0.0
    assert evaluate_ranking(["x"], {"y": 1}, 1)["hit@k"] == 0.0


def test_duplicates_in_ranking_count_once():
    rel = {"a": 1, "b": 1}
    ranking = ["a", "a", "b"]
    assert precision_at_k(ranking, rel, 3) == pytest.approx(2 / 3)
    assert recall_at_k(ranking, rel, 3) == 1.0
    assert ndcg_at_k(ranking, rel, 3) == pytest.approx(1.0)


def test_k_must_be_positive():
    for fn in (precision_at_k, recall_at_k, reciprocal_rank, ndcg_at_k):
        with pytest.raises(ValueError):
            fn(RANKING, REL, 0)
    with pytest.raises(ValueError):
        evaluate_ranking(RANKING, REL, -1)


def test_evaluate_ranking_matches_single_functions_and_runner_keys():
    out = evaluate_ranking(RANKING, REL, 5)
    assert set(out) == set(METRICS) == {"P@k", "R@k", "MRR", "nDCG@k", "hit@k"}
    assert out["P@k"] == precision_at_k(RANKING, REL, 5)
    assert out["R@k"] == recall_at_k(RANKING, REL, 5)
    assert out["MRR"] == reciprocal_rank(RANKING, REL, 5)
    assert out["nDCG@k"] == ndcg_at_k(RANKING, REL, 5)
    assert out["hit@k"] == 1.0


def test_ranking_accepts_any_sequence():
    assert evaluate_ranking(tuple(RANKING), REL, 5) == evaluate_ranking(RANKING, REL, 5)


def test_all_metrics_stay_in_unit_interval():
    rng = random.Random(7)
    units = [f"u{i}" for i in range(12)]
    for _ in range(200):
        rel = {u: rng.choice([0, 0, 1, 2, 3]) for u in rng.sample(units, rng.randint(0, 12))}
        ranking = rng.sample(units, rng.randint(0, 12))
        k = rng.randint(1, 12)
        out = evaluate_ranking(ranking, rel, k)
        assert all(0.0 <= out[m] <= 1.0 + 1e-12 for m in METRICS), (ranking, rel, k, out)


def test_mean_metrics():
    rows = [evaluate_ranking(["b"], {"b": 1}, 1), evaluate_ranking(["a"], {"b": 1}, 1)]
    mean = mean_metrics(rows)
    assert mean["MRR"] == 0.5 and mean["hit@k"] == 0.5 and mean["P@k"] == 0.5
    assert mean_metrics([]) == {m: 0.0 for m in METRICS}
