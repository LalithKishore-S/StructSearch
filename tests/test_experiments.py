import json
from pathlib import Path

import pytest

from structsearch.config import load_config
from structsearch.experiments import evaluate_ranking, load_labels, load_queries, mean_metrics, parse_variant, run_experiment
from structsearch.experiments.runner import tune_weights, write_results
from structsearch.interface.cli import main

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "experiments" / "sample"
CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def test_metrics_values():
    m = evaluate_ranking(["a", "b", "c"], {"b": 1, "z": 1}, 3)
    assert m["P@k"] == pytest.approx(1 / 3) and m["R@k"] == 0.5 and m["MRR"] == 0.5 and m["hit@k"] == 1
    assert 0 < m["nDCG@k"] < 1
    perfect = evaluate_ranking(["b", "z"], {"b": 1, "z": 1}, 2)
    assert perfect["nDCG@k"] == pytest.approx(1.0)
    none = evaluate_ranking(["a"], {"b": 1}, 1)
    assert none["MRR"] == 0 and none["nDCG@k"] == 0 and none["hit@k"] == 0
    assert evaluate_ranking([], {}, 5)["R@k"] == 0


def test_mean_metrics_empty():
    assert mean_metrics([])["MRR"] == 0.0


def test_parse_variant():
    assert parse_variant("text_ast+llm") == ("text_ast", True)
    assert parse_variant("bm25") == ("bm25", False)
    for bad in ("nope", "bm25+x"):
        with pytest.raises(ValueError):
            parse_variant(bad)


def test_loaders_validate(tmp_path):
    p = tmp_path / "q.json"
    p.write_text(json.dumps([{"query_id": "a", "query": "x", "split": "val"}]))
    with pytest.raises(ValueError):
        load_queries(p)
    p.write_text(json.dumps([{"query_id": "a", "query": "x"}, {"query_id": "a", "query": "y"}]))
    with pytest.raises(ValueError):
        load_queries(p)
    csvf = tmp_path / "l.csv"
    csvf.write_text("query_id,unit_id,relevance,query_category,split\na,u1,1,lexical,dev\n")
    assert load_labels(csvf) == {"a": {"u1": 1}}


def test_run_dev_only_and_test_untouched(tmp_path):
    cfg = load_config()
    qs, labels = load_queries(SAMPLE / "queries.json"), load_labels(SAMPLE / "labels.jsonl")
    res = run_experiment(qs, labels, ["bm25", "text_ast"], cfg, str(CORPUS), str(tmp_path / "i"))
    assert {r["split"] for r in res["per_query"]} == {"dev"}
    assert {r["query_id"] for r in res["per_query"]} == {"d1", "d2", "d3", "d4"}
    s = {(r["variant"], r["category"]): r for r in res["summary"]}
    assert s[("bm25", "all")]["n"] == 4 and ("text_ast", "relationship") in s
    final = run_experiment(qs, labels, ["bm25"], cfg, str(CORPUS), str(tmp_path / "i"), splits=("dev", "test"))
    assert {r["split"] for r in final["per_query"]} == {"dev", "test"}


def test_query_without_relevant_label_is_skipped(tmp_path):
    cfg = load_config()
    qs = load_queries(SAMPLE / "queries.json")
    res = run_experiment(qs, {"d1": {"x": 0}}, ["bm25"], cfg, str(CORPUS), str(tmp_path / "i"))
    assert res["per_query"] == [] and "d1" in res["skipped"]


def test_failures_recorded(tmp_path):
    cfg = load_config()
    qs = load_queries(SAMPLE / "queries.json")[:1]
    res = run_experiment(qs, {"d1": {"utils.py::add": 1}}, ["bm25"], cfg, str(CORPUS), str(tmp_path / "i"))
    assert res["failures"] and res["failures"][0]["top1"] == "trees.py::factorial"


def test_custom_metric_fn(tmp_path):
    cfg = load_config()
    qs, labels = load_queries(SAMPLE / "queries.json"), load_labels(SAMPLE / "labels.jsonl")
    fn = lambda ranking, rel, k: {m: 0.5 for m in ("P@k", "R@k", "MRR", "nDCG@k", "hit@k")}
    res = run_experiment(qs, labels, ["bm25"], cfg, str(CORPUS), str(tmp_path / "i"), metric_fn=fn)
    assert res["summary"][0]["MRR"] == 0.5


def test_tune_uses_dev_only_and_sorted(tmp_path):
    cfg = load_config()
    qs, labels = load_queries(SAMPLE / "queries.json"), load_labels(SAMPLE / "labels.jsonl")
    rows = tune_weights(qs, labels, "text_ast", cfg, str(CORPUS), str(tmp_path / "i"), step=0.5)
    assert rows and all(r["n"] == 4 for r in rows)
    assert all(abs(sum(r["weights"].values()) - 1) < 1e-9 for r in rows)
    vals = [r["nDCG@k"] for r in rows]
    assert vals == sorted(vals, reverse=True)


def test_write_results(tmp_path):
    cfg = load_config()
    qs, labels = load_queries(SAMPLE / "queries.json"), load_labels(SAMPLE / "labels.jsonl")
    res = run_experiment(qs, labels, ["bm25"], cfg, str(CORPUS), str(tmp_path / "i"))
    files = write_results(res, tmp_path / "out", 10)
    assert {f.name for f in files} == {"summary.csv", "per_query.csv", "failures.json", "results.md"}
    assert "| bm25 | dev | all |" in (tmp_path / "out" / "results.md").read_text()


def test_cli_experiment(tmp_path, capsys):
    out = tmp_path / "res"
    code = main(["experiment", "--queries", str(SAMPLE / "queries.json"), "--labels", str(SAMPLE / "labels.jsonl"),
                 "--variants", "bm25,text_ast", "--out", str(out), "--corpus", str(CORPUS),
                 "--index-dir", str(tmp_path / "i")])
    assert code == 0 and (out / "results.md").exists()
    assert "| test |" not in capsys.readouterr().out


def test_cli_experiment_final_and_errors(tmp_path, capsys):
    base = ["experiment", "--queries", str(SAMPLE / "queries.json"), "--labels", str(SAMPLE / "labels.jsonl"),
            "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "i"), "--out", str(tmp_path / "r")]
    assert main(base + ["--variants", "bm25", "--final"]) == 0
    assert "| bm25 | test | all |" in capsys.readouterr().out
    assert main(base + ["--variants", "bogus"]) == 2
    assert main(["experiment", "--queries", str(tmp_path / "none.json"), "--labels", "x"]) == 2
    assert main(base + ["--tune", "text_ast", "--step", "0.5"]) == 0
    assert "weights tuned on dev only" in capsys.readouterr().out
