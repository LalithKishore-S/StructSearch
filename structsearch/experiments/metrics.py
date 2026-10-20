"""Stub evaluator for Step 8 (same idea as Member 2's metrics; swap theirs in via runner(metric_fn=...)).

A ranking is a list of unit_ids (best first). `relevance` maps unit_id -> grade (0 = not relevant).
Units without a label count as not relevant.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Sequence

METRICS = ("P@k", "R@k", "MRR", "nDCG@k", "hit@k")


def evaluate_ranking(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> Dict[str, float]:
    top = list(ranking)[:k]
    grades = [max(int(relevance.get(u, 0)), 0) for u in top]
    total_rel = sum(1 for g in relevance.values() if g > 0)
    hits = sum(1 for g in grades if g > 0)
    first = next((i for i, g in enumerate(grades, 1) if g > 0), None)
    dcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(grades, 1))
    ideal = sorted((g for g in relevance.values() if g > 0), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return {
        "P@k": hits / k if k else 0.0,
        "R@k": hits / total_rel if total_rel else 0.0,
        "MRR": 1.0 / first if first else 0.0,
        "nDCG@k": dcg / idcg if idcg else 0.0,
        "hit@k": 1.0 if hits else 0.0,
    }


def mean_metrics(rows: Iterable[Mapping[str, float]]) -> Dict[str, float]:
    rows = list(rows)
    if not rows:
        return {m: 0.0 for m in METRICS}
    return {m: sum(r[m] for r in rows) / len(rows) for m in METRICS}
