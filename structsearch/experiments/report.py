"""Result tables at several K, and paired comparisons between variants.

`run_experiment` keeps the ranking of every (query, variant); the tables here recompute the metrics from
those rankings at each K, so one run (at the largest K) gives P@K, R@K, MRR, NDCG@K and hit@K for K = 1, 3, 5.

The paired comparison looks at the same queries under two variants (wins / ties / losses of the metric,
mean difference, two-sided sign test). With a few dozen queries the test has little power: read it as a
count of queries that changed, not as proof.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from structsearch.evaluation.metrics import METRICS, evaluate_ranking, mean_metrics

MetricFn = Any
ROW_KEYS = ("variant", "split", "category", "k", "n")


def _categories(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    return ["all"] + sorted({r["category"] for r in rows})


def metrics_by_k(
    per_query: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, int]],
    ks: Sequence[int],
    metric_fn: MetricFn = evaluate_ranking,
) -> List[Dict[str, Any]]:
    """Mean metrics per (variant, split, category, K), recomputed from the stored rankings."""
    out: List[Dict[str, Any]] = []
    variants = list(dict.fromkeys(r["variant"] for r in per_query))
    splits = sorted({r["split"] for r in per_query})
    for variant in variants:
        for split in splits:
            for category in _categories(per_query):
                rows = [r for r in per_query if r["variant"] == variant and r["split"] == split
                        and (category == "all" or r["category"] == category)]
                if not rows:
                    continue
                for k in ks:
                    scores = [metric_fn(r["ranking"], labels[r["query_id"]], k) for r in rows]
                    out.append({"variant": variant, "split": split, "category": category, "k": k, "n": len(rows),
                                **mean_metrics(scores)})
    return out


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact sign test; ties are left out by the caller."""
    n = wins + losses
    if n == 0:
        return 1.0
    low = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(low + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired_comparison(
    per_query: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, int]],
    baseline: str,
    k: int,
    metric: str = "nDCG@k",
    metric_fn: MetricFn = evaluate_ranking,
    epsilon: float = 1e-9,
) -> List[Dict[str, Any]]:
    """Each non-baseline variant against `baseline`, per (split, category): wins / ties / losses on `metric`."""
    variants = list(dict.fromkeys(r["variant"] for r in per_query))
    if baseline not in variants:
        raise ValueError(f"baseline '{baseline}' is not among the variants ({', '.join(variants)})")
    base = {(r["query_id"], r["split"]): r for r in per_query if r["variant"] == baseline}
    out: List[Dict[str, Any]] = []
    for variant in variants:
        if variant == baseline:
            continue
        for split in sorted({r["split"] for r in per_query}):
            for category in _categories(per_query):
                diffs = []
                for r in per_query:
                    if r["variant"] != variant or r["split"] != split or not (category == "all" or r["category"] == category):
                        continue
                    ref = base.get((r["query_id"], split))
                    if ref is None:
                        continue
                    qid = r["query_id"]
                    diffs.append(metric_fn(r["ranking"], labels[qid], k)[metric] - metric_fn(ref["ranking"], labels[qid], k)[metric])
                if not diffs:
                    continue
                wins = sum(d > epsilon for d in diffs)
                losses = sum(d < -epsilon for d in diffs)
                out.append({"variant": variant, "baseline": baseline, "split": split, "category": category, "k": k,
                            "metric": metric, "n": len(diffs), "wins": wins, "ties": len(diffs) - wins - losses,
                            "losses": losses, "mean_diff": sum(diffs) / len(diffs), "p_value": sign_test_p(wins, losses)})
    return out


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], fmt: Mapping[str, str]) -> List[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for r in rows:
        lines.append("| " + " | ".join(format(r[c], fmt.get(c, "")) if not isinstance(r[c], str) else r[c] for c in columns) + " |")
    return lines


def write_report(
    result: Mapping[str, Any],
    labels: Mapping[str, Mapping[str, int]],
    out_dir: Path,
    ks: Sequence[int],
    baseline: Optional[str] = None,
    metric_fn: MetricFn = evaluate_ranking,
) -> List[Path]:
    """summary_by_k.csv, paired.csv and report.md (tables per split and category, then paired comparisons)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    per_query = result["per_query"]
    summary = metrics_by_k(per_query, labels, ks, metric_fn)
    variants = list(dict.fromkeys(r["variant"] for r in per_query))
    baseline = baseline or (variants[0] if variants else "")
    paired: List[Dict[str, Any]] = []
    if baseline in variants and len(variants) > 1:
        for k in ks:
            paired += paired_comparison(per_query, labels, baseline, k, metric_fn=metric_fn)

    files = []
    with open(out / "summary_by_k.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, [*ROW_KEYS, *METRICS])
        w.writeheader()
        for row in summary:
            w.writerow({**row, **{m: round(row[m], 4) for m in METRICS}})
    files.append(out / "summary_by_k.csv")
    paired_cols = ["variant", "baseline", "split", "category", "k", "metric", "n", "wins", "ties", "losses", "mean_diff", "p_value"]
    with open(out / "paired.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, paired_cols)
        w.writeheader()
        for row in paired:
            w.writerow({**row, "mean_diff": round(row["mean_diff"], 4), "p_value": round(row["p_value"], 4)})
    files.append(out / "paired.csv")

    lines = ["# Report", "", f"Variants: {', '.join(variants)}.  K = {', '.join(str(k) for k in ks)}.  "
             "Metrics are recomputed from the rankings of one run.", ""]
    for split in sorted({r["split"] for r in summary}):
        for category in _categories(per_query):
            rows = [r for r in summary if r["split"] == split and r["category"] == category]
            if not rows:
                continue
            lines += [f"## {split} / {category} (n = {rows[0]['n']})", ""]
            for k in ks:
                lines += [f"K = {k}", ""]
                lines += _table([r for r in rows if r["k"] == k], ["variant", *METRICS], {m: ".3f" for m in METRICS}) + [""]
    if paired:
        lines += [f"## Paired comparison against {baseline}", "",
                  "Per query, difference in nDCG@K to the baseline (wins: better than the baseline). "
                  "p is a two-sided sign test over wins and losses; with this few queries it has little power.", ""]
        lines += _table(paired, ["variant", "split", "category", "k", "n", "wins", "ties", "losses", "mean_diff", "p_value"],
                        {"mean_diff": "+.3f", "p_value": ".3f"}) + [""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    files.append(out / "report.md")
    return files
