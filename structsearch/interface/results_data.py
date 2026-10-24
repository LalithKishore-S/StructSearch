"""Data behind the Results tab: the experiment tables and per-query rankings, read from experiments/runs/.

Plain functions (no Streamlit), unit-tested against the committed run. Everything shown comes from the files the
experiment runner wrote (summary_by_k.csv, paired.csv, per_query.csv, run.json) and from the frozen benchmark
(queries and labels); the metrics of a query at another K are recomputed from its stored ranking.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from structsearch.evaluation.labels import read_records
from structsearch.evaluation.metrics import METRICS, evaluate_ranking

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = ROOT / "experiments" / "runs" / "final"
DEFAULT_BENCHMARK = ROOT / "experiments" / "benchmark"

VARIANT_ORDER = ("bm25", "text_ast", "text_graph", "text_ast_graph", "text_ast_graph-text",
                 "text_ast_graph-structural", "text_ast_graph-graph")
VARIANT_LABELS = {
    "bm25": "BM25 (baseline)",
    "text_ast": "Text + AST",
    "text_graph": "Text + Graph",
    "text_ast_graph": "Full (Text + AST + Graph)",
    "text_ast_graph-text": "Full without text",
    "text_ast_graph-structural": "Full without AST structure",
    "text_ast_graph-graph": "Full without graph",
}
ABLATIONS = ("text_ast_graph", "text_ast_graph-text", "text_ast_graph-structural", "text_ast_graph-graph")
FULL = "text_ast_graph"
BASELINE = "bm25"
EPS = 1e-9


@dataclass
class RunData:
    summary: List[Dict[str, Any]]
    paired: List[Dict[str, Any]]
    per_query: List[Dict[str, Any]]
    info: Dict[str, Any]
    queries: Dict[str, Dict[str, Any]]
    labels: Dict[str, Dict[str, int]]
    benchmark_matches_lock: Optional[bool] = None
    notes: List[str] = field(default_factory=list)


def _floats(rows: List[Dict[str, Any]], keys: Sequence[str]) -> List[Dict[str, Any]]:
    for row in rows:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                row[key] = float(row[key])
    return rows


def load_results(run_dir: Optional[Path] = None, benchmark_dir: Optional[Path] = None) -> Optional[RunData]:
    """The experiment run in `run_dir` joined with the benchmark; None if the run files are missing."""
    run_dir, benchmark_dir = Path(run_dir or DEFAULT_RUN), Path(benchmark_dir or DEFAULT_BENCHMARK)
    try:
        summary = _floats(read_records(run_dir / "summary_by_k.csv"), (*METRICS, "n", "k"))
        paired = _floats(read_records(run_dir / "paired.csv"), ("n", "k", "wins", "ties", "losses", "mean_diff", "p_value"))
        per_query = read_records(run_dir / "per_query.csv")
        info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        queries = {r["query_id"]: r for r in read_records(benchmark_dir / "queries.json")}
        labels: Dict[str, Dict[str, int]] = {}
        for r in read_records(benchmark_dir / "labels.jsonl"):
            labels.setdefault(r["query_id"], {})[r["unit_id"]] = int(r["relevance"])
    except (OSError, ValueError, KeyError):
        return None
    for row in per_query:
        row["ranking"] = [u for u in row["ranking"].split(";") if u]
    for row in summary + paired:
        row["n"], row["k"] = int(row["n"]), int(row["k"])
    for row in paired:
        for key in ("wins", "ties", "losses"):
            row[key] = int(row[key])
    matches: Optional[bool] = None
    lock_file = benchmark_dir / "split.lock"
    if lock_file.exists() and info.get("benchmark_lock"):
        try:
            current = json.loads(lock_file.read_text(encoding="utf-8"))
            recorded = info["benchmark_lock"]
            matches = (current.get("queries_sha256") == recorded.get("queries_sha256")
                       and current.get("labels_sha256") == recorded.get("labels_sha256"))
        except (OSError, ValueError):
            matches = None
    return RunData(summary, paired, per_query, info, queries, labels, matches)


def split_note(split: str) -> str:
    if split == "test":
        return "Test split: queries never used for tuning; run once with the frozen weights."
    return "Development split: the fusion weights were tuned on these queries, so the numbers are optimistic."


# --------------------------------------------------------------------------- tables


def metric_rows(run: RunData, split: str, category: str, k: int) -> List[Dict[str, Any]]:
    """One row per variant (in display order) with its metrics at K."""
    rows = {r["variant"]: r for r in run.summary if r["split"] == split and r["category"] == category and r["k"] == k}
    return [{"variant": v, "label": VARIANT_LABELS[v], "n": rows[v]["n"], **{m: rows[v][m] for m in METRICS}}
            for v in VARIANT_ORDER if v in rows]


def ablation_rows(run: RunData, split: str, category: str, k: int, metric: str = "nDCG@k") -> List[Dict[str, Any]]:
    """The full model and the full model with one signal removed, with the change against the full model."""
    rows = {r["variant"]: r for r in metric_rows(run, split, category, k)}
    full = rows[FULL][metric]
    return [{"variant": v, "label": VARIANT_LABELS[v], "value": rows[v][metric], "delta": rows[v][metric] - full}
            for v in ABLATIONS if v in rows]


def paired_rows(run: RunData, split: str, category: str, k: int) -> List[Dict[str, Any]]:
    """Each variant against the baseline: queries won / tied / lost (nDCG@K), mean difference, sign-test p."""
    return [{**r, "label": VARIANT_LABELS[r["variant"]]} for r in run.paired
            if r["split"] == split and r["category"] == category and r["k"] == k and r["variant"] in VARIANT_LABELS]


# --------------------------------------------------------------------------- per query


def _first_relevant(ranking: Sequence[str], relevance: Dict[str, int], k: int) -> Optional[int]:
    for rank, unit in enumerate(list(ranking)[:k], 1):
        if relevance.get(unit, 0) > 0:
            return rank
    return None


def query_outcomes(run: RunData, split: str, variant: str = FULL, baseline: str = BASELINE, k: int = 3) -> List[Dict[str, Any]]:
    """For every query of a split: nDCG@K of the variant and the baseline, the change, and win / tie / loss."""
    rows = {(r["query_id"], r["variant"]): r for r in run.per_query if r["split"] == split}
    out = []
    for qid in sorted({q for q, _ in rows}):
        rel = run.labels[qid]
        base, var = rows[(qid, baseline)]["ranking"], rows[(qid, variant)]["ranking"]
        a, b = evaluate_ranking(base, rel, k)["nDCG@k"], evaluate_ranking(var, rel, k)["nDCG@k"]
        delta = b - a
        out.append({"query_id": qid, "query": run.queries[qid]["query"], "category": run.queries[qid]["category"],
                    "baseline_ndcg": a, "variant_ndcg": b, "delta": delta,
                    "outcome": "win" if delta > EPS else "loss" if delta < -EPS else "tie",
                    "baseline_rank": _first_relevant(base, rel, k), "variant_rank": _first_relevant(var, rel, k)})
    return out


def error_analysis(outcomes: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Queries grouped by what happened: improved over the baseline, regressed, solved by both, or not solved."""
    groups: Dict[str, List[Dict[str, Any]]] = {"improved": [], "regressed": [], "solved": [], "unsolved": []}
    for o in outcomes:
        if o["outcome"] == "win":
            groups["improved"].append(o)
        elif o["outcome"] == "loss":
            groups["regressed"].append(o)
        elif o["variant_ndcg"] >= 1 - EPS:
            groups["solved"].append(o)
        else:
            groups["unsolved"].append(o)
    return groups


def query_detail(run: RunData, query_id: str, k: int) -> Dict[str, Any]:
    """The ranking of every variant for one query, each result marked relevant or not (top K only)."""
    if query_id not in run.queries:
        raise KeyError(query_id)
    rel = run.labels[query_id]
    rows = {r["variant"]: r for r in run.per_query if r["query_id"] == query_id}
    variants = []
    for v in VARIANT_ORDER:
        if v not in rows:
            continue
        ranking = rows[v]["ranking"][:k]
        variants.append({"variant": v, "label": VARIANT_LABELS[v],
                         "ranking": [{"unit_id": u, "relevant": rel.get(u, 0) > 0} for u in ranking],
                         "first_relevant": _first_relevant(ranking, rel, k),
                         "ndcg": evaluate_ranking(rows[v]["ranking"], rel, k)["nDCG@k"]})
    q = run.queries[query_id]
    return {"query_id": query_id, "query": q["query"], "category": q["category"], "split": q["split"],
            "group": q.get("group"), "notes": q.get("notes", ""), "relevant": sorted(u for u, g in rel.items() if g > 0),
            "variants": variants}
