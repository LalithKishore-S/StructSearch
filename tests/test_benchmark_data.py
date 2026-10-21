"""The shipped benchmark: structure checks, and its judgements against facts that can be read from the code."""
from pathlib import Path

import pytest

from structsearch.evaluation import check_benchmark, read_records
from structsearch.graph import build_graph
from structsearch.ingestion import ingest_corpus
from structsearch.parsing import extract_all

ROOT = Path(__file__).parent.parent
BENCH = ROOT / "experiments" / "benchmark"
CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def data():
    units = ingest_corpus(CORPUS).units
    queries = {r["query_id"]: r for r in read_records(BENCH / "queries.json")}
    relevant = {}
    for r in read_records(BENCH / "labels.jsonl"):
        if int(r["relevance"]) > 0:
            relevant.setdefault(r["query_id"], set()).add(r["unit_id"])
    graph = build_graph(units)
    features = {rec.unit_id: rec.features for rec in extract_all(units)}
    return units, queries, relevant, graph, features


def group_relevant(data, group):
    _, queries, relevant, *_ = data
    sets = {frozenset(relevant[q]) for q, rec in queries.items() if rec.get("group") == group}
    assert len(sets) == 1, group
    return set(next(iter(sets)))


def test_shipped_benchmark_is_valid_and_frozen():
    units = ingest_corpus(CORPUS).units
    report = check_benchmark(BENCH / "queries.json", BENCH / "labels.jsonl", [u.unit_id for u in units])
    assert report.problems == [] and report.warnings == [] and report.frozen
    assert 20 <= report.stats["queries"] <= 40 and report.stats["labels"] == report.stats["queries"] * 16


def test_split_sizes_and_balance(data):
    _, queries, *_ = data
    split = {s: [q for q, r in queries.items() if r["split"] == s] for s in ("dev", "test")}
    assert len(split["dev"]) == 20 and len(split["test"]) == 14
    for s, ids in split.items():
        cats = {queries[q]["category"] for q in ids}
        assert cats == {"lexical", "relationship"}, s
    relationship = [q for q, r in queries.items() if r["category"] == "relationship"]
    assert 0.4 <= len(relationship) / len(queries) <= 0.65


def test_paraphrase_groups_are_complete_and_kept_together(data):
    _, queries, *_ = data
    groups = {}
    for qid, rec in queries.items():
        if rec.get("group"):
            groups.setdefault(rec["group"], []).append(qid)
    assert len(groups) >= 6
    for group, members in groups.items():
        assert len(members) >= 2 and len({queries[m]["split"] for m in members}) == 1, group


def test_failed_file_unit_is_never_relevant(data):
    _, _, relevant, *_ = data
    assert all("broken_syntax.py::<module>" not in units for units in relevant.values())


def test_recursion_judgements_match_self_calls(data):
    _, _, _, graph, features = data
    calling_itself = {u for u, f in features.items() if f.get("self_call")}
    assert group_relevant(data, "recursion") == calling_itself
    assert group_relevant(data, "recursive_traversal") == {"trees.py::inorder_traverse"}
    assert {"trees.py::inorder_traverse"} <= calling_itself


def test_file_judgements_match_try_blocks(data):
    _, _, _, graph, features = data
    opens = set(graph.units_with_marker("file:open"))
    with_try = {u for u in opens if features[u]["try_count"] > 0}
    assert group_relevant(data, "file_with_try") == with_try
    assert group_relevant(data, "file_no_try") == opens - with_try


def test_database_judgements_match_marker_order(data):
    _, _, _, graph, _ = data
    executes = set(graph.units_with_marker("db:execute"))

    def first(unit, label):
        return min(e.line for e in graph.markers_of(unit) if e.target == label)

    validated = {u for u in executes if u in graph.units_with_marker("validation:validate")
                 and first(u, "validation:validate") < first(u, "db:execute")}
    assert group_relevant(data, "validate_then_query") == validated
    assert group_relevant(data, "unvalidated_db") == executes - validated
    assert group_relevant(data, "sql_concat") == executes - validated  # both unvalidated functions concatenate


def test_single_query_judgements_match_features(data):
    _, _, relevant, _, features = data
    assert relevant["R11"] == {u for u, f in features.items() if f.get("while_count")}
    assert relevant["R18"] == {u for u, f in features.items() if f.get("raise_count")}
    assert relevant["R15"] == relevant["R11"]
    assert relevant["R12"] == {"db.py::get_user"}


def test_lexical_queries_name_one_task_each(data):
    _, queries, relevant, *_ = data
    lexical = [q for q, r in queries.items() if r["category"] == "lexical"]
    assert len(lexical) == 14
    assert {len(relevant[q]) for q in lexical} == {1, 2}
    assert [q for q in lexical if len(relevant[q]) == 2] == ["L11"]
