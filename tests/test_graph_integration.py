import json
from pathlib import Path

import pytest

from structsearch.config import load_config, validate_config
from structsearch.experiments.runner import Query, load_queries, run_experiment, tune_weights
from structsearch.interface.cli import main
from structsearch.interface.explain import template_explanation
from structsearch.interface.service import (
    MODES,
    SearchError,
    SearchRequest,
    fusion_weights,
    run_search,
)

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"
RELATION_QUERY = "validate user input before database access"
LEXICAL_QUERY = "convert camel case name to snake case"


@pytest.fixture()
def cfg():
    return load_config()


def search(cfg, tmp_path, query, mode="text_graph", **kw):
    req = SearchRequest(query=query, mode=mode, k=kw.pop("k", 5), corpus=str(CORPUS),
                        index_dir=str(tmp_path / "idx"), **kw)
    return run_search(req, cfg)


# ------------------------------------------------------------------ service


def test_mode_is_registered():
    assert "text_graph" in MODES


def test_text_graph_uses_text_and_graph_only(cfg, tmp_path):
    resp = search(cfg, tmp_path, RELATION_QUERY)
    assert resp.extra["fusion"]["signals"] == ["text", "graph"]
    assert resp.extra["graph"] == {"intents": ["validated_db"], "scored_units": 3}
    assert "profile" not in resp.extra
    top = resp.results[0]
    assert top.unit_id == "db.py::get_user" and top.graph_score == 1.0 and top.structural_score == 0.0
    assert "edge: get_user -> validate_user_input (call, line 12)" in top.evidence
    assert "order: validation (line 12) is before database access (line 13)" in top.evidence


def test_graph_lifts_the_unit_that_does_validate_then_query(cfg, tmp_path):
    ranking = [r.unit_id for r in search(cfg, tmp_path, "validate input before database access", k=4).results]
    assert ranking.index("db.py::get_user") < ranking.index("db.py::validate_user_input")


def test_query_without_relationship_ranks_like_bm25(cfg, tmp_path):
    graph = search(cfg, tmp_path, LEXICAL_QUERY)
    bm25 = search(cfg, tmp_path, LEXICAL_QUERY, mode="bm25")
    assert graph.extra["graph"]["intents"] == [] and graph.extra["fusion"]["signals"] == ["text"]
    assert [r.unit_id for r in graph.results] == [r.unit_id for r in bm25.results]
    assert all(r.graph_score is None for r in graph.results)


def test_explicit_intents_replace_the_query_reading(cfg, tmp_path):
    resp = search(cfg, tmp_path, "tree", intents=["recursive"], k=10)
    assert resp.extra["graph"]["intents"] == ["recursive"]
    graph_units = {r.unit_id for r in resp.results if r.graph_score}
    assert graph_units == {"trees.py::factorial", "trees.py::inorder_traverse"}


def test_unknown_intent_is_a_search_error(cfg, tmp_path):
    with pytest.raises(SearchError) as err:
        search(cfg, tmp_path, "tree", intents=["telepathy"])
    assert err.value.code == 2


def test_text_ast_is_unchanged_by_the_graph(cfg, tmp_path):
    resp = search(cfg, tmp_path, RELATION_QUERY, mode="text_ast")
    assert "graph" not in resp.extra["fusion"]["signals"] and "graph" not in resp.extra
    assert all(r.graph_score is None for r in resp.results)


def test_hybrid_includes_the_graph(cfg, tmp_path):
    resp = search(cfg, tmp_path, RELATION_QUERY, mode="hybrid", embedder="hashing")
    assert resp.extra["fusion"]["signals"] == ["text", "dense", "structural", "graph"]
    assert resp.extra["graph"]["intents"] == ["validated_db"]
    lexical = search(cfg, tmp_path, LEXICAL_QUERY, mode="hybrid", embedder="hashing")
    assert "graph" not in lexical.extra["fusion"]["signals"]


def test_graph_weight_can_be_overridden_or_zeroed(cfg, tmp_path):
    zero = search(cfg, tmp_path, RELATION_QUERY, weights=["graph=0"])
    assert "graph" not in zero.extra["fusion"]["weights"] and zero.extra["fusion"]["signals"] == ["text"]  # removed
    heavy = search(cfg, tmp_path, RELATION_QUERY, weights=["text=0", "graph=1"])
    assert heavy.extra["fusion"]["weights"] == {"graph": 1.0}  # a zero weight removes the signal
    assert [r.unit_id for r in heavy.results] == ["db.py::get_user", "db.py::count_rows", "db.py::find_user_unsafe"]


def test_weights_per_mode(cfg):
    assert fusion_weights("text_graph", cfg, []) == cfg["text_graph_weights"]
    assert fusion_weights("text_graph", cfg, ["graph=0.9"]) == {"text": cfg["text_graph_weights"]["text"], "graph": 0.9}
    assert "dense" in fusion_weights("hybrid", cfg, []) and "dense" not in fusion_weights("text_ast", cfg, [])
    without = {k: v for k, v in cfg.items() if k != "text_graph_weights"}
    assert fusion_weights("text_graph", without, []) == {"text": 0.7, "graph": 0.3}


def test_config_validation_of_text_graph_weights(cfg):
    validate_config(cfg)
    for bad in ({"text": 1}, {"text": 1, "graph": -1}, {"text": 0, "graph": 0}):
        broken = {**cfg, "text_graph_weights": bad}
        with pytest.raises(ValueError):
            validate_config(broken)


def test_tolerant_corpus_still_searchable(cfg, tmp_path):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")
    corpus = Path(__file__).parent / "fixtures" / "tolerant_corpus"
    req = SearchRequest(query="recursive", mode="text_graph", k=5, corpus=str(corpus),
                        index_dir=str(tmp_path / "idx"), tolerant=True)
    resp = run_search(req, cfg)
    assert resp.extra["graph"]["intents"] == ["recursive"]
    assert resp.results[0].unit_id == "broken_service.py::Repo.good_method"


# ------------------------------------------------------------------ command line


def run_cli(capsys, tmp_path, *args):
    code = main(["search", *args, "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "idx")])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_text_graph_json(capsys, tmp_path):
    code, out, err = run_cli(capsys, tmp_path, RELATION_QUERY, "--mode", "text_graph", "--json", "-k", "3", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and payload["graph"]["intents"] == ["validated_db"]
    assert payload["results"][0]["graph_score"] == 1.0
    assert "graph relationships: validated_db" in err


def test_cli_text_output_shows_graph_evidence(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, RELATION_QUERY, "--mode", "text_graph", "-k", "1", "--lines", "0")
    assert code == 0 and "edge: get_user -> validate_user_input (call, line 12)" in out


def test_cli_intent_flag(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "tree", "--mode", "text_graph", "--intent", "recursive", "--json", "-k", "10", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and payload["graph"]["intents"] == ["recursive"]
    with pytest.raises(SystemExit):
        run_cli(capsys, tmp_path, "tree", "--mode", "text_graph", "--intent", "telepathy")


def test_cli_note_when_query_has_no_relationship(capsys, tmp_path):
    code, out, err = run_cli(capsys, tmp_path, LEXICAL_QUERY, "--mode", "text_graph", "-k", "2", "--lines", "0")
    assert code == 0 and "no relationship the call graph can express" in err


def test_explanation_quotes_graph_evidence(cfg, tmp_path):
    resp = search(cfg, tmp_path, RELATION_QUERY, k=1)
    result = resp.results[0]
    exp = template_explanation(result, resp.units_by_id[result.unit_id])
    assert any(p.startswith("Call-graph evidence:") and "get_user -> validate_user_input" in p for p in exp.points)
    assert exp.cited


def test_explain_flag_with_text_graph(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, RELATION_QUERY, "--mode", "text_graph", "--explain", "-k", "1", "--lines", "0")
    assert code == 0 and "why: db.py::get_user" in out


# ------------------------------------------------------------------ experiment runner


def write_inputs(tmp_path):
    queries = [
        {"query_id": "r1", "query": RELATION_QUERY, "category": "relationship", "split": "dev"},
        {"query_id": "r2", "query": "tree", "category": "relationship", "split": "dev", "intents": ["recursive"]},
        {"query_id": "l1", "query": LEXICAL_QUERY, "category": "lexical", "split": "dev"},
        {"query_id": "t1", "query": "opens a file", "category": "relationship", "split": "test"},
    ]
    labels = [
        ("r1", "db.py::get_user", 1), ("r2", "trees.py::factorial", 1), ("r2", "trees.py::inorder_traverse", 1),
        ("l1", "utils.py::camel_to_snake", 1), ("t1", "files.py::read_lines", 1),
    ]
    qp, lp = tmp_path / "q.json", tmp_path / "l.jsonl"
    qp.write_text(json.dumps(queries))
    lp.write_text("\n".join(json.dumps({"query_id": q, "unit_id": u, "relevance": r, "query_category": "x", "split": "dev"})
                            for q, u, r in labels))
    return qp, lp


def test_queries_file_can_carry_intents(tmp_path):
    qp, _ = write_inputs(tmp_path)
    by_id = {q.query_id: q for q in load_queries(qp)}
    assert by_id["r2"].intents == ["recursive"] and by_id["r1"].intents == []
    assert isinstance(by_id["r1"], Query)


def test_text_graph_variant_in_the_runner(cfg, tmp_path):
    from structsearch.experiments.runner import load_labels

    qp, lp = write_inputs(tmp_path)
    result = run_experiment(load_queries(qp), load_labels(lp), ["bm25", "text_ast", "text_graph"], cfg,
                            str(CORPUS), str(tmp_path / "idx"), k=3)
    rows = {(r["variant"], r["category"]): r for r in result["summary"]}
    assert rows[("text_graph", "all")]["n"] == 3 and rows[("text_graph", "relationship")]["n"] == 2
    assert rows[("text_graph", "all")]["MRR"] == pytest.approx(1.0)
    test_rows = [r for r in result["per_query"] if r["split"] == "test"]
    assert test_rows == []  # the test split stays untouched without --final


def test_tune_weights_for_text_graph(cfg, tmp_path):
    from structsearch.experiments.runner import load_labels

    qp, lp = write_inputs(tmp_path)
    rows = tune_weights(load_queries(qp), load_labels(lp), "text_graph", cfg, str(CORPUS), str(tmp_path / "idx"), k=3, step=0.5)
    assert {tuple(sorted(r["weights"])) for r in rows} == {("graph", "text")}
    assert all(abs(sum(r["weights"].values()) - 1) < 1e-9 for r in rows) and len(rows) == 3
    assert rows[0]["nDCG@k"] >= rows[-1]["nDCG@k"]


def test_tune_weights_for_hybrid_includes_the_graph(cfg, tmp_path):
    from structsearch.experiments.runner import TUNED_SIGNALS

    assert TUNED_SIGNALS["hybrid"] == ["text", "dense", "structural", "graph"]
    assert TUNED_SIGNALS["text_ast"] == ["text", "structural"]


def test_cli_experiment_with_text_graph(capsys, tmp_path):
    qp, lp = write_inputs(tmp_path)
    code = main(["experiment", "--queries", str(qp), "--labels", str(lp), "--corpus", str(CORPUS),
                 "--index-dir", str(tmp_path / "idx"), "--out", str(tmp_path / "res"), "--variants", "bm25,text_graph", "-k", "3"])
    out = capsys.readouterr().out
    assert code == 0 and "| text_graph | dev | all |" in out
    assert (tmp_path / "res" / "summary.csv").exists()


# ------------------------------------------------------------------ structured graph result for front ends


def test_response_carries_the_graph_result_only_in_graph_modes(cfg, tmp_path):
    resp = search(cfg, tmp_path, RELATION_QUERY)
    assert resp.graph_result is not None and resp.graph_result.intents == ["validated_db"]
    assert "db.py::get_user" in resp.graph_result.edges
    assert search(cfg, tmp_path, RELATION_QUERY, mode="text_ast").graph_result is None
    assert search(cfg, tmp_path, RELATION_QUERY, mode="bm25").graph_result is None


def test_cli_json_stays_free_of_structured_edges(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, RELATION_QUERY, "--mode", "text_graph", "--json", "-k", "2", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and set(payload["graph"]) == {"intents", "scored_units"}
