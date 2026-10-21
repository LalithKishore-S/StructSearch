import csv
import json
import math
from pathlib import Path

import pytest

from structsearch.config import load_config, validate_config
from structsearch.evaluation import evaluate_ranking
from structsearch.experiments.report import (
    metrics_by_k,
    paired_comparison,
    sign_test_p,
    write_report,
)
from structsearch.experiments.runner import (
    TUNED_SIGNALS,
    Query,
    load_labels,
    load_queries,
    parse_variant,
    run_experiment,
    tune_weights,
    variant_ablations,
)
from structsearch.interface.cli import main
from structsearch.interface.service import MODES, SearchRequest, fusion_weights, run_search

ROOT = Path(__file__).parent.parent
BENCH = ROOT / "experiments" / "benchmark"
CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"
RELATION_QUERY = "validate user input before database access"


@pytest.fixture()
def cfg():
    return load_config()


# ------------------------------------------------------------------ the full text + AST + graph mode


def test_text_ast_graph_mode_uses_all_three_signals(cfg, tmp_path):
    assert "text_ast_graph" in MODES
    req = SearchRequest(query=RELATION_QUERY, mode="text_ast_graph", k=3, corpus=str(CORPUS), index_dir=str(tmp_path / "i"))
    resp = run_search(req, cfg)
    assert resp.extra["fusion"]["signals"] == ["text", "structural", "graph"]
    assert resp.extra["graph"]["intents"] == ["validated_db"] and "profile" in resp.extra
    assert all(r.graph_score is not None for r in resp.results)


def test_text_ast_graph_weights_and_validation(cfg):
    assert set(fusion_weights("text_ast_graph", cfg, [])) == {"text", "structural", "graph"}
    assert fusion_weights("text_ast_graph", {k: v for k, v in cfg.items() if k != "text_ast_graph_weights"}, []) == {
        "text": 0.5, "structural": 0.25, "graph": 0.25}
    validate_config(cfg)
    for bad in ({"text": 1, "graph": 1}, {"text": 1, "structural": -1, "graph": 0}, {"text": 0, "structural": 0, "graph": 0}):
        with pytest.raises(ValueError):
            validate_config({**cfg, "text_ast_graph_weights": bad})


def test_tuned_signals_per_mode():
    assert TUNED_SIGNALS["text_ast_graph"] == ["text", "structural", "graph"]


# ------------------------------------------------------------------ ablation variants


def test_ablation_syntax():
    assert parse_variant("text_ast_graph-graph") == ("text_ast_graph", False)
    assert parse_variant("text_ast_graph+llm-structural") == ("text_ast_graph", True)
    assert variant_ablations("text_ast_graph-graph-structural") == ["graph", "structural"]
    assert variant_ablations("bm25") == []
    for bad in ("text_ast-graph", "bm25-text", "text_ast_graph-nothing", "text_ast_graph-text-structural-graph", "nope-text"):
        with pytest.raises(ValueError):
            parse_variant(bad)


def test_removing_graph_from_the_full_mode_matches_text_ast(cfg, tmp_path):
    queries = [Query("r1", RELATION_QUERY, "relationship", "dev"), Query("r2", "function that calls itself", "relationship", "dev")]
    labels = {"r1": {"db.py::get_user": 1}, "r2": {"trees.py::factorial": 1}}
    # equal text:structural ratio in both configurations, so only the graph differs
    cfg = {**cfg, "weights": {"text": 0.6, "structural": 0.3, "graph": 0.1},
           "text_ast_graph_weights": {"text": 0.5, "structural": 0.25, "graph": 0.25}}
    res = run_experiment(queries, labels, ["text_ast", "text_ast_graph-graph", "text_ast_graph"], cfg,
                         str(CORPUS), str(tmp_path / "i"), k=5)
    ranking = {(r["query_id"], r["variant"]): r["ranking"] for r in res["per_query"]}
    for qid in ("r1", "r2"):
        assert ranking[(qid, "text_ast")] == ranking[(qid, "text_ast_graph-graph")]


def test_removing_text_leaves_structure_and_graph_only(cfg, tmp_path):
    req = SearchRequest(query=RELATION_QUERY, mode="text_ast_graph", k=3, corpus=str(CORPUS),
                        index_dir=str(tmp_path / "i"), weights=["text=0"])
    resp = run_search(req, cfg)
    assert resp.extra["fusion"]["signals"] == ["structural", "graph"] and "text" not in resp.extra["fusion"]["weights"]
    assert all(r.text_score == 0.0 for r in resp.results)


# ------------------------------------------------------------------ tables at several K


def per_query_rows():
    rows = []
    data = {
        ("q1", "relationship", "dev"): {"A": ["x", "y", "z"], "B": ["y", "x", "z"]},
        ("q2", "lexical", "dev"): {"A": ["p", "q"], "B": ["p", "q"]},
    }
    for (qid, cat, split), per in data.items():
        for variant, ranking in per.items():
            rows.append({"query_id": qid, "category": cat, "split": split, "variant": variant, "ranking": ranking})
    return rows


LABELS = {"q1": {"x": 1}, "q2": {"p": 1}}


def test_metrics_by_k_recomputes_from_the_stored_rankings():
    rows = metrics_by_k(per_query_rows(), LABELS, (1, 3))
    by = {(r["variant"], r["category"], r["k"]): r for r in rows}
    assert by[("A", "relationship", 1)]["MRR"] == 1.0 and by[("B", "relationship", 1)]["MRR"] == 0.0
    assert by[("B", "relationship", 3)]["MRR"] == pytest.approx(0.5)
    assert by[("A", "all", 3)]["n"] == 2 and by[("A", "all", 3)]["MRR"] == 1.0
    assert by[("B", "all", 3)]["MRR"] == pytest.approx(0.75)
    direct = evaluate_ranking(["y", "x", "z"], {"x": 1}, 3)
    assert by[("B", "relationship", 3)]["nDCG@k"] == pytest.approx(direct["nDCG@k"])


def test_sign_test():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(3, 3) == 1.0
    assert sign_test_p(5, 0) == pytest.approx(0.0625)
    assert sign_test_p(0, 5) == pytest.approx(0.0625)
    assert sign_test_p(8, 2) == pytest.approx(0.109375)


def test_paired_comparison_counts_wins_ties_losses():
    rows = paired_comparison(per_query_rows(), LABELS, "A", k=3)
    by = {(r["variant"], r["category"]): r for r in rows}
    b_rel = by[("B", "relationship")]
    assert (b_rel["wins"], b_rel["ties"], b_rel["losses"]) == (0, 0, 1)
    assert by[("B", "lexical")]["ties"] == 1 and by[("B", "all")]["losses"] == 1
    assert by[("B", "all")]["mean_diff"] == pytest.approx(-(1 - 1 / math.log2(3)) / 2)  # q1: nDCG 1.0 -> 0.631, q2: tie
    assert b_rel["mean_diff"] < 0 and b_rel["p_value"] == 1.0 and "A" not in {r["variant"] for r in rows}


def test_paired_comparison_rejects_unknown_baseline():
    with pytest.raises(ValueError):
        paired_comparison(per_query_rows(), LABELS, "nope", k=3)


def test_write_report_files(tmp_path):
    paths = write_report({"per_query": per_query_rows()}, LABELS, tmp_path, (1, 3), "A")
    names = {p.name for p in paths}
    assert names == {"summary_by_k.csv", "paired.csv", "report.md"}
    rows = list(csv.DictReader((tmp_path / "summary_by_k.csv").open()))
    assert {r["k"] for r in rows} == {"1", "3"} and {"variant", "split", "category", "n", "MRR"} <= set(rows[0])
    text = (tmp_path / "report.md").read_text()
    assert "K = 1" in text and "Paired comparison against A" in text and "wins" in text


# ------------------------------------------------------------------ tuning


def test_tuning_prefers_text_on_ties(cfg, tmp_path):
    queries = load_queries(BENCH / "queries.json")
    labels = load_labels(BENCH / "labels.jsonl")
    rows = tune_weights(queries, labels, "text_graph", cfg, str(CORPUS), str(tmp_path / "i"), k=3, step=0.5)
    assert len(rows) == 3
    best = [r for r in rows if r["nDCG@k"] == rows[0]["nDCG@k"] and r["MRR"] == rows[0]["MRR"]]
    assert rows[0]["weights"]["text"] == max(r["weights"]["text"] for r in best)


def test_tuning_never_reads_the_test_split(cfg, tmp_path):
    queries = load_queries(BENCH / "queries.json")
    labels = load_labels(BENCH / "labels.jsonl")
    # remove all test labels: tuning must be unaffected
    test_ids = {q.query_id for q in queries if q.split == "test"}
    pruned = {k: v for k, v in labels.items() if k not in test_ids}
    a = tune_weights(queries, labels, "text_ast", cfg, str(CORPUS), str(tmp_path / "a"), k=3, step=0.5)
    b = tune_weights(queries, pruned, "text_ast", cfg, str(CORPUS), str(tmp_path / "b"), k=3, step=0.5)
    assert a == b


# ------------------------------------------------------------------ command line


def run_cli(capsys, tmp_path, *extra):
    code = main(["experiment", "--queries", str(BENCH / "queries.json"), "--labels", str(BENCH / "labels.jsonl"),
                 "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "idx"), "--out", str(tmp_path / "out"), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_ks_and_ablations_write_the_report(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--variants", "bm25,text_ast_graph,text_ast_graph-graph", "--ks", "1,3,5")
    assert code == 0
    for name in ("summary_by_k.csv", "paired.csv", "report.md", "run.json", "results.md"):
        assert (tmp_path / "out" / name).exists(), name
    run = json.loads((tmp_path / "out" / "run.json").read_text())
    assert run["ks"] == [1, 3, 5] and run["splits"] == ["dev"] and run["baseline"] == "bm25"
    assert run["benchmark_lock"]["queries"] == 34 and "text_ast_graph_weights" in run["weights"]
    assert "text_ast_graph-graph" in (tmp_path / "out" / "report.md").read_text()
    # the test split stays untouched without --final
    assert all(r["split"] == "dev" for r in csv.DictReader((tmp_path / "out" / "summary_by_k.csv").open()))


def test_cli_rejects_a_bad_ks_value(capsys, tmp_path):
    code, _, err = run_cli(capsys, tmp_path, "--variants", "bm25", "--ks", "1,x")
    assert code == 2 and "--ks" in err


def test_cli_tune_writes_a_log(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--tune", "text_ast_graph", "--step", "0.5", "-k", "3")
    assert code == 0 and "tuned on dev only" in out
    log = (tmp_path / "out" / "tuning_text_ast_graph.md").read_text()
    assert "| text | structural | graph |" in log and "dev only" in log


def test_text_only_fusion_is_the_bm25_baseline_on_every_benchmark_query(cfg, tmp_path):
    """The baseline of every comparison: removing the other signals must leave exactly the BM25 ranking."""
    queries = load_queries(BENCH / "queries.json")
    labels = load_labels(BENCH / "labels.jsonl")
    weight_sets = {"text_ast_graph": ["structural=0", "graph=0"], "text_ast": ["structural=0"], "text_graph": ["graph=0"]}
    res = run_experiment(queries, labels, ["bm25", "text_ast_graph", "text_ast", "text_graph"], cfg, str(CORPUS),
                         str(tmp_path / "i"), k=5, splits=("dev",), weight_sets=weight_sets)
    by = {}
    for r in res["per_query"]:
        by.setdefault(r["query_id"], {})[r["variant"]] = r["ranking"]
    assert len(by) == 20
    for qid, rankings in by.items():
        for variant in ("text_ast_graph", "text_ast", "text_graph"):
            assert rankings[variant] == rankings["bm25"], (qid, variant)


def test_tuning_with_a_minimum_weight_keeps_every_signal(cfg, tmp_path):
    queries = load_queries(BENCH / "queries.json")
    labels = load_labels(BENCH / "labels.jsonl")
    free = tune_weights(queries, labels, "text_ast_graph", cfg, str(CORPUS), str(tmp_path / "i"), k=3, step=0.25)
    kept = tune_weights(queries, labels, "text_ast_graph", cfg, str(CORPUS), str(tmp_path / "i"), k=3, step=0.25,
                        min_weight=0.25)
    assert any(min(r["weights"].values()) == 0 for r in free)
    assert kept and all(min(r["weights"].values()) >= 0.25 for r in kept)
    assert len(kept) == 3 and len(free) == 15  # compositions of 4 steps over 3 signals, and those with each part >= 1
    assert kept[0]["nDCG@k"] <= free[0]["nDCG@k"]


def test_cli_min_weight_writes_a_separate_log(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--tune", "text_ast_graph", "--step", "0.25", "--min-weight", "0.25", "-k", "3")
    assert code == 0
    log = (tmp_path / "out" / "tuning_text_ast_graph_min0.25.md").read_text()
    assert "every signal keeps a weight of at least 0.25" in log
    assert not (tmp_path / "out" / "tuning_text_ast_graph.md").exists()
