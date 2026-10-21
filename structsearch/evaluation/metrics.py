"""Ranking metrics: Precision@K, Recall@K, MRR and NDCG@K.

A ranking is a list of unit_ids (best first). `relevance` maps unit_id -> grade (0 = not relevant,
1 = relevant, higher grades allowed). Units without a label count as not relevant.

Conventions (identical for every variant, so numbers are comparable):
  - Only the first `k` entries are looked at; a unit that appears twice counts once, at its first position.
  - P@K divides by K, also when fewer than K results were returned.
  - R@K divides by the number of relevant units in the label pool for the query (0 if there are none).
  - MRR is the reciprocal rank of the first relevant unit inside the top K (0 if there is none); the mean
    over queries is taken by `mean_metrics`.
  - NDCG@K uses gain 2^grade - 1 and discount log2(rank + 1), normalized by the ideal ordering of the
    labelled relevant units. For 0/1 labels this is the usual binary NDCG.
  - hit@K is 1 if any relevant unit is in the top K.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Sequence

METRICS = ("P@k", "R@k", "MRR", "nDCG@k", "hit@k")


def _check_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError(f"k must be a positive integer, got {k!r}")


def _top(ranking: Sequence[str], k: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for unit_id in ranking:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        out.append(unit_id)
        if len(out) == k:
            break
    return out


def _grades(top: Sequence[str], relevance: Mapping[str, int]) -> List[int]:
    return [max(int(relevance.get(u, 0)), 0) for u in top]


def _relevant_total(relevance: Mapping[str, int]) -> int:
    return sum(1 for g in relevance.values() if int(g) > 0)


def precision_at_k(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    _check_k(k)
    return sum(1 for g in _grades(_top(ranking, k), relevance) if g > 0) / k


def recall_at_k(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    _check_k(k)
    total = _relevant_total(relevance)
    if not total:
        return 0.0
    return sum(1 for g in _grades(_top(ranking, k), relevance) if g > 0) / total


def reciprocal_rank(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    _check_k(k)
    for rank, grade in enumerate(_grades(_top(ranking, k), relevance), 1):
        if grade > 0:
            return 1.0 / rank
    return 0.0


def _dcg(grades: Iterable[int]) -> float:
    return sum((2 ** g - 1) / math.log2(rank + 1) for rank, g in enumerate(grades, 1))


def ndcg_at_k(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    _check_k(k)
    ideal = sorted((int(g) for g in relevance.values() if int(g) > 0), reverse=True)[:k]
    best = _dcg(ideal)
    if best <= 0:
        return 0.0
    return min(_dcg(_grades(_top(ranking, k), relevance)) / best, 1.0)


def evaluate_ranking(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> Dict[str, float]:
    """All metrics for one query; the signature `run_experiment` expects of a `metric_fn`."""
    _check_k(k)
    hits = any(g > 0 for g in _grades(_top(ranking, k), relevance))
    return {
        "P@k": precision_at_k(ranking, relevance, k),
        "R@k": recall_at_k(ranking, relevance, k),
        "MRR": reciprocal_rank(ranking, relevance, k),
        "nDCG@k": ndcg_at_k(ranking, relevance, k),
        "hit@k": 1.0 if hits else 0.0,
    }


def mean_metrics(rows: Iterable[Mapping[str, float]]) -> Dict[str, float]:
    """Mean of each metric over per-query results (MRR becomes the mean reciprocal rank)."""
    rows = list(rows)
    if not rows:
        return {m: 0.0 for m in METRICS}
    return {m: sum(r[m] for r in rows) / len(rows) for m in METRICS}
