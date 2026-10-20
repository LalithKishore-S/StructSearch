"""Step 8 experiment runner: variants x queries -> per-query metrics, tables, failures.

Queries file (JSON list or JSONL): {"query_id","query","category","split"[, "patterns":[...]]}
Labels file (JSON list, JSONL or CSV), EvaluationLabel fields: query_id, unit_id, relevance, query_category, split.
Variant names: bm25 | dense | structural | like | text_ast | hybrid, optionally "+llm" (query mapped by Ollama,
falls back to rules), e.g. "text_ast+llm". Fusion weights can be overridden per variant via `weight_sets`.
"""
from __future__ import annotations

import csv
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from structsearch.experiments.metrics import METRICS, evaluate_ranking, mean_metrics
from structsearch.interface.service import MODES, SearchError, SearchRequest, run_search
from structsearch.llm.ollama import LLMSettings

MetricFn = Callable[[Sequence[str], Mapping[str, int], int], Dict[str, float]]


@dataclass
class Query:
    query_id: str
    query: str
    category: str = "lexical"
    split: str = "dev"
    patterns: List[str] = field(default_factory=list)


def _read_records(path: Path) -> List[Dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".csv"):
        return list(csv.DictReader(text.splitlines()))
    stripped = text.lstrip()
    if stripped.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_queries(path: Path) -> List[Query]:
    out, seen = [], set()
    for rec in _read_records(path):
        q = Query(
            str(rec["query_id"]), str(rec["query"]), rec.get("category") or rec.get("query_category") or "lexical",
            rec.get("split", "dev"), list(rec.get("patterns") or []),
        )
        if q.split not in ("dev", "test"):
            raise ValueError(f"{q.query_id}: split must be dev or test")
        if q.query_id in seen:
            raise ValueError(f"duplicate query_id {q.query_id}")
        seen.add(q.query_id)
        out.append(q)
    return out


def load_labels(path: Path) -> Dict[str, Dict[str, int]]:
    """query_id -> {unit_id: relevance}."""
    out: Dict[str, Dict[str, int]] = {}
    for rec in _read_records(path):
        out.setdefault(str(rec["query_id"]), {})[str(rec["unit_id"])] = int(rec["relevance"])
    return out


def parse_variant(name: str) -> Tuple[str, bool]:
    base, plus, flag = name.partition("+")
    if base not in MODES:
        raise ValueError(f"unknown variant '{name}' (modes: {', '.join(MODES)})")
    if plus and flag != "llm":
        raise ValueError(f"unknown variant suffix '+{flag}' (only +llm)")
    return base, bool(plus)


def _rank(variant: str, q: Query, k: int, corpus: str, index_dir: str, cfg: Mapping[str, Any],
          llm: LLMSettings, embedder: Optional[str], weights: List[str]) -> List[str]:
    mode, use_llm = parse_variant(variant)
    settings = LLMSettings(**{**llm.__dict__, "enabled": True}) if use_llm else LLMSettings(**{**llm.__dict__, "enabled": False})
    req = SearchRequest(query=q.query, mode=mode, k=k, corpus=corpus, index_dir=index_dir, query_id=q.query_id,
                        embedder=embedder, llm=settings, patterns=q.patterns, weights=weights)
    return [r.unit_id for r in run_search(req, dict(cfg)).results]


def run_experiment(
    queries: Sequence[Query],
    labels: Mapping[str, Mapping[str, int]],
    variants: Sequence[str],
    cfg: Mapping[str, Any],
    corpus: str,
    index_dir: str,
    k: int = 10,
    splits: Sequence[str] = ("dev",),
    llm: Optional[LLMSettings] = None,
    embedder: Optional[str] = None,
    weight_sets: Optional[Mapping[str, List[str]]] = None,
    metric_fn: MetricFn = evaluate_ranking,
) -> Dict[str, Any]:
    """Returns {"per_query": [...], "summary": [...], "failures": [...], "skipped": [...]}.
    Only queries in `splits` are run, so test queries stay untouched until asked for."""
    llm = llm or LLMSettings.from_config(dict(cfg))
    per_query: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for q in queries:
        if q.split not in splits:
            continue
        rel = labels.get(q.query_id)
        if not rel or not any(g > 0 for g in rel.values()):
            skipped.append(q.query_id)  # no relevant unit labelled: metrics would be meaningless
            continue
        for variant in variants:
            ranking = _rank(variant, q, k, corpus, index_dir, cfg, llm, embedder, list((weight_sets or {}).get(variant, [])))
            scores = metric_fn(ranking, rel, k)
            per_query.append({"query_id": q.query_id, "category": q.category, "split": q.split, "variant": variant,
                              "ranking": ranking, **scores})
            if scores["hit@k"] == 0 or (ranking and rel.get(ranking[0], 0) <= 0):
                missed = [u for u, g in rel.items() if g > 0 and u not in ranking]
                failures.append({
                    "query_id": q.query_id, "query": q.query, "variant": variant, "category": q.category,
                    "kind": "no relevant result in top-k" if scores["hit@k"] == 0 else "top-1 not relevant",
                    "top1": ranking[0] if ranking else None,
                    "relevant_missing": missed,
                })
    summary: List[Dict[str, Any]] = []
    for variant in variants:
        for split in splits:
            for cat in ["all"] + sorted({r["category"] for r in per_query}):
                rows = [r for r in per_query if r["variant"] == variant and r["split"] == split
                        and (cat == "all" or r["category"] == cat)]
                if rows:
                    summary.append({"variant": variant, "split": split, "category": cat, "n": len(rows),
                                    **mean_metrics(rows)})
    return {"per_query": per_query, "summary": summary, "failures": failures, "skipped": skipped}


def tune_weights(
    queries: Sequence[Query], labels: Mapping[str, Mapping[str, int]], mode: str, cfg: Mapping[str, Any],
    corpus: str, index_dir: str, k: int = 10, step: float = 0.25, embedder: Optional[str] = None,
    metric: str = "nDCG@k",
) -> List[Dict[str, Any]]:
    """Grid search over fusion weights on DEV queries only. Returns rows sorted best first."""
    names = ["text", "dense", "structural"] if mode == "hybrid" else ["text", "structural"]
    n = int(round(1 / step))
    grid = [c for c in itertools.product(range(n + 1), repeat=len(names)) if sum(c) == n]
    rows = []
    for combo in grid:
        weights = [f"{name}={c / n}" for name, c in zip(names, combo)] + ["graph=0"]
        res = run_experiment(queries, labels, [mode], cfg, corpus, index_dir, k, ("dev",), embedder=embedder,
                             weight_sets={mode: weights})
        s = next((x for x in res["summary"] if x["category"] == "all"), None)
        if s:
            rows.append({"weights": dict(zip(names, [c / n for c in combo])), **{m: s[m] for m in METRICS}, "n": s["n"]})
    return sorted(rows, key=lambda r: (-r[metric], -r["MRR"], json.dumps(r["weights"])))


def write_results(result: Mapping[str, Any], out_dir: Path, k: int) -> List[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["variant", "split", "category", "n", *METRICS])
        w.writeheader()
        for row in result["summary"]:
            w.writerow({**row, **{m: round(row[m], 4) for m in METRICS}})
    files.append(out / "summary.csv")
    with open(out / "per_query.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["query_id", "split", "category", "variant", *METRICS, "ranking"])
        w.writeheader()
        for row in result["per_query"]:
            w.writerow({**{c: row[c] for c in ("query_id", "split", "category", "variant")},
                        **{m: round(row[m], 4) for m in METRICS}, "ranking": ";".join(row["ranking"])})
    files.append(out / "per_query.csv")
    (out / "failures.json").write_text(json.dumps(result["failures"], indent=2), encoding="utf-8")
    files.append(out / "failures.json")
    lines = [f"# Results (k={k})", "", "| variant | split | category | n | " + " | ".join(METRICS) + " |",
             "|---|---|---|---|" + "---|" * len(METRICS)]
    for r in result["summary"]:
        lines.append(f"| {r['variant']} | {r['split']} | {r['category']} | {r['n']} | "
                     + " | ".join(f"{r[m]:.3f}" for m in METRICS) + " |")
    if result["skipped"]:
        lines += ["", "Skipped (no relevant label): " + ", ".join(result["skipped"])]
    lines += ["", f"## Failures ({len(result['failures'])})", ""]
    for fl in result["failures"]:
        lines.append(f"- {fl['query_id']} [{fl['variant']}] {fl['kind']}: \"{fl['query']}\" top1={fl['top1']} "
                     f"missing={fl['relevant_missing']}")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files.append(out / "results.md")
    return files
