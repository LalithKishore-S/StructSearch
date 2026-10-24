import re
from pathlib import Path

import pytest

from structsearch.config import load_config
from structsearch.graph import CodeGraph, GraphEdge, GraphNode, build_graph, ensure_graph
from structsearch.ingestion import ingest_corpus
from structsearch.interface.service import SearchRequest, run_search
from structsearch.interface.ui_data import (
    COLOR_EVIDENCE,
    DEMO_QUERIES,
    LEGEND,
    breakdown_long,
    candidate_rows,
    evidence_graph_dot,
    full_graph_dot,
    score_breakdown,
    understand_query,
    unit_card,
)
from structsearch.security import scan_sql_candidates

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def graph():
    return build_graph(ingest_corpus(CORPUS).units)


def search(cfg, tmp_path_factory, query, mode="text_ast_graph", k=5, **kw):
    req = SearchRequest(query=query, mode=mode, k=k, corpus=str(CORPUS), index_dir=str(tmp_path_factory.mktemp("idx")), **kw)
    return run_search(req, cfg)


@pytest.fixture(scope="module")
def relation(cfg, tmp_path_factory):
    return search(cfg, tmp_path_factory, "validate user input before database access")


# ------------------------------------------------------------------ understanding the query


def test_understanding_a_relationship_query(relation):
    info = understand_query("validate user input before database access", "text_ast_graph", relation.extra, relation.graph_result)
    assert info["uses_graph"] and [i["name"] for i in info["intents"]] == ["validated_db"]
    assert info["trace"]["validation"] == ["validate"] and info["trace"]["database"] == ["database"]
    assert info["graph_note"] is None and info["signals"] == ["text", "structural", "graph"]
    assert sum(info["weights"].values()) == pytest.approx(1.0)
    assert info["structure"] and "validation" in info["structure"][0]


def test_understanding_a_query_without_relationship(cfg, tmp_path_factory):
    resp = search(cfg, tmp_path_factory, "convert camel case name to snake case")
    info = understand_query("convert camel case name to snake case", "text_ast_graph", resp.extra, resp.graph_result)
    assert info["intents"] == [] and "left out" in info["graph_note"] and "graph" not in info["signals"]


def test_understanding_a_mode_without_the_graph(cfg, tmp_path_factory):
    resp = search(cfg, tmp_path_factory, "validate user input", mode="bm25")
    info = understand_query("validate user input", "bm25", resp.extra, resp.graph_result)
    assert not info["uses_graph"] and info["intents"] == [] and info["signals"] == [] and info["weights"] == {}


def test_relationship_without_a_matching_function():
    from structsearch.graph import score_graph
    empty = score_graph(CodeGraph([GraphNode("a.py::f", "f", "f", "a.py", "ok")], []), "opens a file")
    info = understand_query("opens a file", "text_graph", {}, empty)
    assert [i["name"] for i in info["intents"]] == ["file_access"] and "no function" in info["graph_note"]


# ------------------------------------------------------------------ score breakdown


def test_contributions_add_up_to_the_final_score(relation):
    weights = relation.extra["fusion"]["weights"]
    rows = score_breakdown(relation.results, weights)
    assert [r["unit_id"] for r in rows] == [r.unit_id for r in relation.results]
    for row in rows:
        assert sum(row["contributions"].values()) == pytest.approx(row["final"], abs=1e-9)
        assert set(row["contributions"]) <= {"text", "structural", "graph"}
    assert rows[0]["rank"] == 1 and rows[0]["name"] == "get_user"


def test_breakdown_without_fusion_has_just_the_score(cfg, tmp_path_factory):
    resp = search(cfg, tmp_path_factory, "validate user input", mode="bm25")
    rows = score_breakdown(resp.results, {})
    assert all(list(r["contributions"]) == ["score"] for r in rows)


def test_breakdown_long_format(relation):
    long = breakdown_long(score_breakdown(relation.results, relation.extra["fusion"]["weights"]))
    assert {"result", "signal", "contribution", "rank"} <= set(long[0])
    assert {r["signal"] for r in long} <= {"text (BM25)", "structure (AST)", "call graph"}
    assert long[0]["result"] == "#1 get_user"


# ------------------------------------------------------------------ evidence graph


def braces_balanced(dot: str) -> bool:
    return dot.count("{") == dot.count("}") and dot.startswith("digraph G {") and dot.endswith("}")


def test_evidence_graph_shows_the_edges_the_ranking_used(relation, graph):
    dot = evidence_graph_dot(graph, relation.results, relation.graph_result)
    assert braces_balanced(dot)
    assert "validate_user_input" in dot and "db:execute" in dot and "validation:validate" in dot
    assert "shape=diamond" in dot and '"line 12"' in dot and '"line 13"' in dot
    assert COLOR_EVIDENCE in dot and "#1 get_user" in dot and re.search(r"score \d\.\d\d", dot)


def test_focus_highlights_only_that_results_evidence(relation, graph):
    others = [r.unit_id for r in relation.results if r.unit_id != "db.py::get_user"]
    focused = evidence_graph_dot(graph, relation.results, relation.graph_result, focus=others[0])
    assert focused.count(COLOR_EVIDENCE) < evidence_graph_dot(graph, relation.results, relation.graph_result).count(COLOR_EVIDENCE)


def test_without_a_graph_result_only_the_results_are_drawn(relation, graph):
    dot = evidence_graph_dot(graph, relation.results, None)
    assert braces_balanced(dot) and COLOR_EVIDENCE not in dot and "#1 get_user" in dot
    with_context = evidence_graph_dot(graph, relation.results, None, show_context=True)
    assert "db:execute" in with_context and COLOR_EVIDENCE not in with_context


def test_context_edges_are_grey_and_added_on_request(relation, graph):
    base = evidence_graph_dot(graph, relation.results, relation.graph_result)
    more = evidence_graph_dot(graph, relation.results, relation.graph_result, show_context=True)
    assert more.count("->") >= base.count("->") and braces_balanced(more)


def test_node_cap(relation, graph):
    dot = evidence_graph_dot(graph, relation.results, relation.graph_result, max_nodes=2)
    assert braces_balanced(dot) and dot.count("shape=box") <= 2


def test_labels_are_escaped():
    node = GraphNode('a.py::say"hi"\\x', 'say"hi"', 'say"hi"', 'a.py', "ok")
    g = CodeGraph([node], [GraphEdge(node.unit_id, "db:execute", "uses_api", "ast_marker_call", 3, "db.execute")])
    from structsearch.schemas import RankedResult
    from structsearch.graph import GraphResult
    res = RankedResult("q", node.unit_id, final_score=0.5)
    dot = evidence_graph_dot(g, [res], GraphResult({node.unit_id: 1.0}, {}, ["db_access"], {node.unit_id: list(g.edges)}))
    assert braces_balanced(dot) and 'say\\"hi\\"' in dot and 'say"hi"' not in dot.replace('say\\"hi\\"', "")


def test_full_graph_groups_by_file_and_filters(graph):
    dot = full_graph_dot(graph)
    assert braces_balanced(dot) and dot.count("subgraph cluster_") == 5 and "db:execute" in dot
    only = full_graph_dot(graph, file_filter="trees.py")
    assert only.count("subgraph cluster_") == 1 and "validate_user_input" not in only
    marked = full_graph_dot(graph, highlight="db.py::get_user")
    assert COLOR_EVIDENCE in marked and "#ffe0e0" in marked


def test_unit_card(graph):
    card = unit_card(graph, "db.py::get_user")
    assert card["calls"] == [("db.py::validate_user_input", 12)] and card["called_by"] == []
    assert [m[:2] for m in card["markers"]] == [("validation:validate", 12), ("db:execute", 13)]
    assert unit_card(graph, "db.py::validate_user_input")["called_by"] == [("db.py::get_user", 12)]
    assert unit_card(graph, "nope")["found"] is False


def test_legend_mentions_every_visual_element():
    for word in ("diamond", "dashed", "solid", "red", "grey", "rank"):
        assert word in LEGEND


# ------------------------------------------------------------------ security rows


def test_candidate_rows(graph):
    units = ingest_corpus(CORPUS).units
    rows = candidate_rows(scan_sql_candidates(units, graph))
    assert [r["function"] for r in rows] == ["db.py::count_rows", "db.py::find_user_unsafe"]
    assert rows[0]["level"] == "high" and "table_name" in rows[0]["source"] and "db:execute" in rows[0]["sink"]


# ------------------------------------------------------------------ the demo queries and their expected answers


@pytest.mark.parametrize("demo", DEMO_QUERIES, ids=[d["label"] for d in DEMO_QUERIES])
def test_demo_query_expected_answers_hold(demo, cfg, tmp_path_factory):
    """The answers promised in the app are checked against the real ranking, so they cannot drift."""
    assert demo["query"] and demo["note"] and demo["kind"] in ("works", "partial", "limit", "empty")
    resp = search(cfg, tmp_path_factory, demo["query"], k=5)
    names = [r.unit_id.split("::")[1] for r in resp.results]
    units = {u.name for u in ingest_corpus(CORPUS).units}
    assert set(demo["expected"]) <= units
    if demo["kind"] in ("works", "partial"):
        assert names and names[0] in demo["expected"], names
        if demo["kind"] == "works":
            assert set(demo["expected"]) <= set(names[: max(len(demo["expected"]), 3)]), names
    elif demo["kind"] == "limit":
        assert not names or names[0] not in demo["expected"], names  # documented failure
    else:
        assert names == []
