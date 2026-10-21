from pathlib import Path

import pytest

from structsearch.graph import (
    DECAY,
    INTENT_DOC,
    GraphResult,
    build_graph,
    graph_intents,
    score_graph,
)
from structsearch.ingestion import ingest_corpus
from structsearch.parsing import extract_all
from structsearch.retrieval.fusion import fused_search, graph_signal

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def fixture():
    units = ingest_corpus(CORPUS).units
    return build_graph(units), units


def make(tmp_path, source):
    (tmp_path / "m.py").write_text(source)
    units = ingest_corpus(tmp_path).units
    return build_graph(units), units


# ------------------------------------------------------------------ query -> intents


@pytest.mark.parametrize("query, expected", [
    ("validate user input before database access", ["validated_db"]),
    ("Find functions validating input before database access", ["validated_db"]),
    ("validation before sql query", ["validated_db"]),
    ("database access without validation", ["unvalidated_db"]),
    ("sql injection", ["unvalidated_db"]),
    ("find possible paths from external input to SQL query construction with weak/missing validation", ["unvalidated_db"]),
    ("unvalidated user input reaching the database", ["unvalidated_db"]),
    ("functions that query the database", ["db_access"]),
    ("check input", ["calls_validator"]),
    ("sanitize values", ["calls_validator"]),
    ("opens a file", ["file_access"]),
    ("recursive tree traversal", ["recursive"]),
    ("function that calls itself", ["recursive"]),
    ("recursive directory walk that opens files", ["file_access", "recursive"]),
    ("convert camel case name to snake case", []),
    ("", []),
])
def test_graph_intents(query, expected):
    assert graph_intents(query) == expected


def test_every_intent_is_documented():
    for intent in ("validated_db", "unvalidated_db", "db_access", "calls_validator", "file_access", "recursive"):
        assert INTENT_DOC[intent]
    assert DECAY == {0: 1.0, 1: 0.7, 2: 0.5, 3: 0.35}


# ------------------------------------------------------------------ the sample corpus


def test_validation_before_database_access(fixture):
    graph, _ = fixture
    result = score_graph(graph, "validate user input before database access")
    assert result.intents == ["validated_db"]
    assert result.scores == {
        "db.py::get_user": 1.0,
        "db.py::find_user_unsafe": 0.25,
        "db.py::count_rows": 0.25,
    }
    assert "db.py::validate_user_input" not in result.scores  # the validator alone never touches the database


def test_validated_unit_evidence_is_factual(fixture):
    graph, _ = fixture
    lines = score_graph(graph, "validate user input before database access").evidence["db.py::get_user"]
    assert lines == [
        "edge: get_user -> validate_user_input (call, line 12)",
        "marker: validation:validate at line 12 (validate_user_input)",
        "marker: db:execute at line 13 (db.execute)",
        "order: validation (line 12) is before database access (line 13)",
    ]
    unsafe = score_graph(graph, "validate user input before database access").evidence["db.py::find_user_unsafe"]
    assert unsafe == [
        "marker: db:execute at line 19 (db.execute)",
        "order: no validation step in find_user_unsafe",
    ]


def test_unvalidated_database_access(fixture):
    graph, _ = fixture
    result = score_graph(graph, "database access without validation")
    assert result.scores == {"db.py::find_user_unsafe": 1.0, "db.py::count_rows": 1.0}
    assert result.evidence["db.py::count_rows"][-1] == "order: no validation step before database access (line 24)"


def test_database_access_and_file_access(fixture):
    graph, _ = fixture
    assert score_graph(graph, "query the database").scores == {
        "db.py::get_user": 1.0, "db.py::find_user_unsafe": 1.0, "db.py::count_rows": 1.0}
    assert score_graph(graph, "opens a file").scores == {
        "files.py::read_config_safe": 1.0, "files.py::read_lines": 1.0, "files.py::write_log": 1.0}


def test_validator_callers_and_recursion(fixture):
    graph, _ = fixture
    assert score_graph(graph, "check the input").scores == {"db.py::get_user": 1.0}
    result = score_graph(graph, "recursive traversal")
    assert result.scores == {"trees.py::factorial": 1.0, "trees.py::inorder_traverse": 1.0}
    assert result.evidence["trees.py::factorial"] == ["edge: factorial -> factorial (call, line 21)"]


def test_no_relationship_in_the_query_means_no_graph_signal(fixture):
    graph, _ = fixture
    result = score_graph(graph, "convert camel case name to snake case")
    assert isinstance(result, GraphResult) and result.intents == [] and result.scores == {} and result.evidence == {}


def test_explicit_intents_and_unknown_intent(fixture):
    graph, _ = fixture
    assert score_graph(graph, intents=["recursive"]).scores == score_graph(graph, "recursive").scores
    with pytest.raises(ValueError):
        score_graph(graph, intents=["telepathy"])
    with pytest.raises(ValueError):
        score_graph(graph)


def test_scores_are_positive_and_deterministic(fixture):
    graph, _ = fixture
    first = score_graph(graph, "validate input before database access")
    second = score_graph(graph, "validate input before database access")
    assert first.scores == second.scores and first.evidence == second.evidence
    assert all(v > 0 for v in first.scores.values())


# ------------------------------------------------------------------ resolution of the ordering


def test_validation_not_before_database_access(tmp_path):
    graph, _ = make(tmp_path, (
        "def after(db, x):\n    db.execute('q')\n    validate(x)\n\n"
        "def same_line(db, x):\n    return db.execute(validate(x))\n\n"
        "def before(db, x):\n    validate(x)\n    return db.execute('q')\n"
    ))
    scores = score_graph(graph, "validate input before database access").scores
    assert scores == {"m.py::before": 1.0, "m.py::after": 0.4, "m.py::same_line": 0.4}
    ev = score_graph(graph, "validate input before database access").evidence["m.py::after"]
    assert ev[-1] == "order: validation (line 3) is not before database access (line 2)"
    assert score_graph(graph, "database access without validation").scores == {"m.py::after": 1.0, "m.py::same_line": 1.0}


def test_database_access_through_callees_decays(tmp_path):
    graph, _ = make(tmp_path, (
        "def run_sql(db, q):\n    return db.execute(q)\n\n"
        "def handler(db, x):\n    validate(x)\n    return run_sql(db, x)\n\n"
        "def other(db):\n    return run_sql(db, 1)\n\n"
        "def top(db):\n    return other(db)\n\n"
        "def far(db):\n    return top(db)\n\n"
        "def too_far(db):\n    return far(db)\n"
    ))
    assert score_graph(graph, "database").scores == {
        "m.py::run_sql": 1.0, "m.py::handler": 0.7, "m.py::other": 0.7, "m.py::top": 0.5, "m.py::far": 0.35}
    validated = score_graph(graph, "validate input before database access").scores
    assert validated["m.py::handler"] == pytest.approx(0.7)
    assert validated["m.py::other"] == pytest.approx(0.25 * 0.7)
    ev = score_graph(graph, "validate input before database access").evidence["m.py::handler"]
    assert "edge: handler -> run_sql (call, line 6)" in ev
    assert "marker: db:execute at line 2 in run_sql (db.execute)" in ev


def test_callee_that_validates_counts_as_a_validation_step(tmp_path):
    graph, units = make(tmp_path, (
        "def ensure_ok(x):\n    if not x:\n        raise ValueError('x')\n    return x\n\n"
        "def save(db, x):\n    ensure_ok(x)\n    return db.execute('q')\n"
    ))
    plain = score_graph(graph, "validate input before database access").scores
    assert plain == {"m.py::save": 0.25}  # the name says nothing about validation
    records = extract_all(units)
    result = score_graph(graph, "validate input before database access", ast_records=records)
    assert result.scores == {"m.py::save": 1.0}
    assert "structure: ensure_ok has guard clauses that raise (AST)" in result.evidence["m.py::save"]


# ------------------------------------------------------------------ recursion, several intents


def test_mutual_recursion_scores_lower_than_self_calls(tmp_path):
    graph, _ = make(tmp_path, (
        "def even(n):\n    return n == 0 or odd(n - 1)\n\ndef odd(n):\n    return n != 0 and even(n - 1)\n\n"
        "def selfy(n):\n    return selfy(n - 1)\n\ndef plain(n):\n    return n\n"
    ))
    result = score_graph(graph, "recursive")
    assert result.scores == {"m.py::even": 0.8, "m.py::odd": 0.8, "m.py::selfy": 1.0}
    assert result.evidence["m.py::even"] == ["edge: even -> odd (call, line 2)", "edge: odd -> even (call, line 5)"]


def test_several_intents_are_averaged(tmp_path):
    graph, _ = make(tmp_path, (
        "def walk(p):\n    open(p)\n    return walk(p)\n\n"
        "def only_rec(p):\n    return only_rec(p)\n\ndef only_open(p):\n    return open(p)\n"
    ))
    result = score_graph(graph, "recursive directory walk that opens files")
    assert result.intents == ["file_access", "recursive"]
    assert result.scores == {"m.py::walk": 1.0, "m.py::only_rec": 0.5, "m.py::only_open": 0.5}


def test_cycle_through_failed_units_is_ignored(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n")
    graph, _ = make(tmp_path, "def f(x):\n    return x\n")
    assert score_graph(graph, "recursive").scores == {}


# ------------------------------------------------------------------ fusion hook


def test_graph_signal_carries_evidence():
    signal = graph_signal({"a": 1.0}, {"a": ["edge: a -> b (call, line 1)"]})
    assert signal.evidence("a") == ["edge: a -> b (call, line 1)"] and signal.evidence("zzz") == []
    assert graph_signal({"a": 1.0}).evidence is None
    assert graph_signal({}) is None and graph_signal(None) is None


def test_fused_search_shows_graph_evidence(fixture, tmp_path):
    from structsearch.indexing.bm25 import BM25Index
    from structsearch.indexing.records import build_text_records

    graph, units = fixture
    index = BM25Index.build(build_text_records(units))
    result = score_graph(graph, "validate user input before database access")
    outcome = fused_search(
        "validate user input before database access", {u.unit_id: u for u in units}, index,
        {"text": 0.6, "graph": 0.4}, k=3, graph_scores=result.scores, graph_evidence=result.evidence)
    assert outcome.active == ["text", "graph"]
    top = outcome.results[0]
    assert top.unit_id == "db.py::get_user" and top.graph_score == 1.0
    assert "edge: get_user -> validate_user_input (call, line 12)" in top.evidence


# ------------------------------------------------------------------ validation inside a callee


WRAPPER = (
    "def validate(x):\n    if not x:\n        raise ValueError('x')\n    return x\n\n"
    "def get_user(db, name):\n    validate(name)\n    return db.execute('SELECT 1 WHERE n = ?', (name,))\n\n"
    "def handler(db, name):\n    return get_user(db, name)\n\n"
    "def raw(db, name):\n    return db.execute('SELECT 1 WHERE n = ' + name)\n\n"
    "def raw_wrapper(db, name):\n    return raw(db, name)\n"
)


def test_wrapper_of_a_validating_function_counts_as_validated(tmp_path):
    graph, _ = make(tmp_path, WRAPPER)
    validated = score_graph(graph, "validate input before database access")
    assert validated.scores["m.py::get_user"] == 1.0
    assert validated.scores["m.py::handler"] == pytest.approx(0.7)  # depth 1, validation happens in the callee
    assert validated.scores["m.py::raw_wrapper"] == pytest.approx(0.25 * 0.7)
    assert "order: validation in get_user (line 7) is before database access (line 8)" in validated.evidence["m.py::handler"]


def test_wrapper_of_a_validating_function_is_not_unvalidated(tmp_path):
    graph, _ = make(tmp_path, WRAPPER)
    unvalidated = score_graph(graph, "database access without validation").scores
    assert set(unvalidated) == {"m.py::raw", "m.py::raw_wrapper"}
    assert unvalidated["m.py::raw_wrapper"] == pytest.approx(0.7)


def test_validation_two_calls_down_still_counts(tmp_path):
    graph, _ = make(tmp_path, WRAPPER + "\ndef outer(db, name):\n    return handler(db, name)\n")
    assert score_graph(graph, "validate input before database access").scores["m.py::outer"] == pytest.approx(0.5)
    assert "m.py::outer" not in score_graph(graph, "database access without validation").scores
