import json
from pathlib import Path

import pytest

from structsearch.graph import (
    METHOD_CALL_NAME,
    METHOD_CLASS_METHOD,
    METHOD_CONSTRUCTOR,
    METHOD_SELF_METHOD,
    REL_CALLS,
    CodeGraph,
    build_graph,
    ensure_graph,
    load_graph,
    save_graph,
)
from structsearch.ingestion import ingest_corpus
from structsearch.interface.cli import main

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def _lines_containing(path: Path, text: str):
    return [n for n, line in enumerate(path.read_text().split("\n"), 1) if text in line]


def make(tmp_path, files):
    for name, source in files.items():
        (tmp_path / name).write_text(source)
    return build_graph(ingest_corpus(tmp_path).units)


def targets(graph, source, relation=REL_CALLS):
    return [e.target for e in graph.edges_from(source, relation)]


@pytest.fixture(scope="module")
def fixture_graph():
    result = ingest_corpus(CORPUS)
    return build_graph(result.units), result.units


# ------------------------------------------------------------------ the sample corpus


def test_every_unit_is_a_node(fixture_graph):
    graph, units = fixture_graph
    assert set(graph.nodes) == {u.unit_id for u in units}
    assert graph.nodes["db.py::get_user"].qualname == "get_user"
    assert graph.nodes["trees.py::Node.__init__"].qualname == "Node.__init__"


def test_validator_call_edge(fixture_graph):
    graph, _ = fixture_graph
    (edge,) = graph.edges_from("db.py::get_user", REL_CALLS)
    assert (edge.target, edge.method) == ("db.py::validate_user_input", METHOD_CALL_NAME)
    assert edge.line == _lines_containing(CORPUS / "db.py", "validate_user_input(username)")[0]
    assert graph.has_edge("db.py::get_user", "db.py::validate_user_input", REL_CALLS)
    assert graph.callers("db.py::validate_user_input") == ["db.py::get_user"]


def test_self_calls(fixture_graph):
    graph, _ = fixture_graph
    (edge,) = graph.edges_from("trees.py::factorial")
    assert edge.target == "trees.py::factorial"
    assert edge.line == _lines_containing(CORPUS / "trees.py", "n * factorial(n - 1)")[0]
    recursive = graph.edges_from("trees.py::inorder_traverse")
    assert [e.target for e in recursive] == ["trees.py::inorder_traverse"] * 2
    assert [e.line for e in recursive] == _lines_containing(CORPUS / "trees.py", "inorder_traverse(node.")


def test_callback_parameter_is_not_a_call_to_the_corpus(fixture_graph):
    graph, _ = fixture_graph
    # inorder_traverse(node, visit) calls its parameter `visit`, never a corpus function
    assert set(targets(graph, "trees.py::inorder_traverse")) == {"trees.py::inorder_traverse"}


def test_units_without_corpus_calls_have_no_call_edges(fixture_graph):
    graph, _ = fixture_graph
    for unit_id in ("trees.py::count_nodes", "db.py::find_user_unsafe", "db.py::count_rows", "utils.py::add",
                    "files.py::read_lines", "files.py::read_config_safe", "utils.py::slugify"):
        assert graph.edges_from(unit_id, REL_CALLS) == [], unit_id


def test_exact_edge_set_of_the_sample_corpus(fixture_graph):
    graph, _ = fixture_graph
    assert sorted((e.source, e.target) for e in graph.edges if e.relation == REL_CALLS) == sorted([
        ("db.py::get_user", "db.py::validate_user_input"),
        ("trees.py::factorial", "trees.py::factorial"),
        ("trees.py::inorder_traverse", "trees.py::inorder_traverse"),
        ("trees.py::inorder_traverse", "trees.py::inorder_traverse"),
    ])
    assert graph.ambiguous == []


def test_failed_unit_is_a_node_without_edges(fixture_graph):
    graph, _ = fixture_graph
    node = graph.nodes["broken_syntax.py::<module>"]
    assert node.parse_status == "failed"
    assert graph.edges_from(node.unit_id) == [] and graph.edges_to(node.unit_id) == []


def test_queries_on_unknown_units_are_empty(fixture_graph):
    graph, _ = fixture_graph
    assert graph.edges_from("nope::x") == [] and graph.callers("nope::x") == [] and graph.callees("nope::x") == []


def test_callees_are_distinct_and_in_call_order(fixture_graph):
    graph, _ = fixture_graph
    assert graph.callees("trees.py::inorder_traverse") == ["trees.py::inorder_traverse"]


# ------------------------------------------------------------------ resolution rules


def test_cross_file_unique_name(tmp_path):
    graph = make(tmp_path, {"a.py": "def helper():\n    return 1\n", "b.py": "def run():\n    return helper()\n"})
    assert targets(graph, "b.py::run") == ["a.py::helper"]


def test_same_file_wins_over_other_files(tmp_path):
    graph = make(tmp_path, {
        "a.py": "def helper():\n    return 1\n\ndef run():\n    return helper()\n",
        "b.py": "def helper():\n    return 2\n",
    })
    assert targets(graph, "a.py::run") == ["a.py::helper"]
    assert graph.ambiguous == []


def test_ambiguous_name_gives_no_edge_and_is_listed(tmp_path):
    graph = make(tmp_path, {
        "a.py": "def helper():\n    return 1\n",
        "b.py": "def helper():\n    return 2\n",
        "c.py": "def run():\n    return helper()\n",
    })
    assert graph.edges == []
    (amb,) = graph.ambiguous
    assert (amb.source, amb.name, amb.candidates, amb.line) == ("c.py::run", "helper", ("a.py::helper", "b.py::helper"), 2)


def test_parameter_and_local_names_shadow_corpus_functions(tmp_path):
    graph = make(tmp_path, {
        "a.py": "def visit():\n    return 1\n\ndef shadow_param(visit):\n    return visit()\n\n"
                "def shadow_local():\n    visit = len\n    return visit([1])\n\ndef real():\n    return visit()\n",
    })
    assert targets(graph, "a.py::shadow_param") == []
    assert targets(graph, "a.py::shadow_local") == []
    assert targets(graph, "a.py::real") == ["a.py::visit"]


def test_self_and_cls_methods(tmp_path):
    source = (
        "class Repo:\n"
        "    def load(self):\n        return self.parse()\n\n"
        "    def parse(self):\n        return 1\n\n"
        "    @classmethod\n    def make(cls):\n        return cls.parse(cls)\n\n"
        "    def missing(self):\n        return self.inherited()\n"
    )
    graph = make(tmp_path, {"r.py": source})
    (edge,) = graph.edges_from("r.py::Repo.load")
    assert (edge.target, edge.method, edge.line) == ("r.py::Repo.parse", METHOD_SELF_METHOD, 3)
    assert targets(graph, "r.py::Repo.make") == ["r.py::Repo.parse"]
    assert targets(graph, "r.py::Repo.missing") == []  # inherited methods are not resolved


def test_self_method_does_not_leak_to_other_classes(tmp_path):
    source = (
        "class A:\n    def go(self):\n        return self.step()\n\n    def step(self):\n        return 1\n\n"
        "class B:\n    def step(self):\n        return 2\n"
    )
    graph = make(tmp_path, {"m.py": source})
    assert targets(graph, "m.py::A.go") == ["m.py::A.step"]


def test_class_name_method_call_and_constructor(tmp_path):
    source = (
        "class Box:\n    def __init__(self, v):\n        self.v = v\n\n    @staticmethod\n    def build(v):\n        return Box(v)\n\n"
        "def use():\n    b = Box(1)\n    return Box.build(2)\n"
    )
    graph = make(tmp_path, {"b.py": source})
    edges = {(e.target, e.method) for e in graph.edges_from("b.py::use")}
    assert edges == {("b.py::Box.__init__", METHOD_CONSTRUCTOR), ("b.py::Box.build", METHOD_CLASS_METHOD)}
    assert targets(graph, "b.py::Box.build") == ["b.py::Box.__init__"]


def test_other_receivers_are_not_resolved(tmp_path):
    source = (
        "def helper():\n    return 1\n\n"
        "def run(obj):\n    obj.helper()\n    return super().helper()\n"
    )
    graph = make(tmp_path, {"a.py": source})
    assert graph.edges == []


def test_alias_is_not_resolved(tmp_path):
    source = "def helper():\n    return 1\n\ndef run():\n    g = helper\n    return g()\n"
    assert make(tmp_path, {"a.py": source}).edges == []


def test_failed_file_unit_is_never_a_target(tmp_path):
    graph = make(tmp_path, {"broken.py": "def (:\n", "a.py": "def run():\n    return broken()\n"})
    assert graph.nodes["broken.py::<module>"].parse_status == "failed"
    assert graph.edges == []


def test_calls_in_nested_functions_and_lambdas_belong_to_the_unit(tmp_path):
    source = "def helper():\n    return 1\n\ndef run():\n    def inner():\n        return helper()\n    return lambda: helper()\n"
    graph = make(tmp_path, {"a.py": source})
    assert [(e.target, e.line) for e in graph.edges_from("a.py::run")] == [("a.py::helper", 6), ("a.py::helper", 7)]


def test_decorators_are_not_calls_of_the_unit(tmp_path):
    source = "def deco(f):\n    return f\n\n@deco\ndef run():\n    return 1\n"
    assert make(tmp_path, {"a.py": source}).edges == []


def test_line_numbers_for_decorated_and_indented_units(tmp_path):
    source = (
        "def helper():\n    return 1\n\n"
        "class C:\n"
        "    @staticmethod\n"
        "    def run():\n"
        "        x = 1\n"
        "        return helper()\n"
    )
    graph = make(tmp_path, {"a.py": source})
    (edge,) = graph.edges_from("a.py::C.run")
    assert edge.line == 8


def test_every_call_site_is_an_edge_in_order(tmp_path):
    source = "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef run():\n    b()\n    a()\n    b()\n"
    graph = make(tmp_path, {"m.py": source})
    assert [(e.target, e.line) for e in graph.edges_from("m.py::run")] == [("m.py::b", 8), ("m.py::a", 9), ("m.py::b", 10)]
    assert graph.callees("m.py::run") == ["m.py::b", "m.py::a"]


def test_duplicate_definitions_are_ambiguous(tmp_path):
    source = "def f():\n    return 1\n\ndef f():\n    return 2\n\ndef run():\n    return f()\n"
    graph = make(tmp_path, {"a.py": source})
    assert graph.edges == []
    assert graph.ambiguous[0].candidates == ("a.py::f", "a.py::f#2")


def test_build_is_deterministic(tmp_path):
    files = {"a.py": "def x():\n    return y()\n\ndef y():\n    return x()\n"}
    first = make(tmp_path, files)
    second = build_graph(ingest_corpus(tmp_path).units)
    assert first.to_dict() == second.to_dict()


# ------------------------------------------------------------------ persistence and cache


def test_round_trip(tmp_path, fixture_graph):
    graph, _ = fixture_graph
    path = tmp_path / "graph.json"
    save_graph(graph, path, "fp")
    fingerprint, loaded = load_graph(path)
    assert fingerprint == "fp" and loaded.to_dict() == graph.to_dict()
    assert CodeGraph.from_dict(json.loads(json.dumps(graph.to_dict()))).to_dict() == graph.to_dict()


def test_round_trip_keeps_ambiguous_calls(tmp_path):
    files = {"a.py": "def h():\n    return 1\n", "b.py": "def h():\n    return 2\n", "c.py": "def r():\n    return h()\n"}
    graph = make(tmp_path, files)
    restored = CodeGraph.from_dict(json.loads(json.dumps(graph.to_dict())))
    assert restored.ambiguous == graph.ambiguous and restored.ambiguous


def test_load_rejects_missing_corrupt_and_old_version(tmp_path):
    assert load_graph(tmp_path / "none.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert load_graph(bad) is None
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"_meta": {"graph_version": "0", "fingerprint": "x"}, "nodes": [], "edges": []}))
    assert load_graph(old) is None


def test_ensure_graph_caches_and_invalidates(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.py").write_text("def x():\n    return 1\n")
    index = tmp_path / "idx"
    graph, reason = ensure_graph(ingest_corpus(corpus).units, index)
    assert reason == "no graph yet" and graph.edges == []
    _, reason = ensure_graph(ingest_corpus(corpus).units, index)
    assert reason is None
    (corpus / "a.py").write_text("def x():\n    return y()\n\ndef y():\n    return 1\n")
    graph, reason = ensure_graph(ingest_corpus(corpus).units, index)
    assert reason == "units or markers changed" and len(graph.edges) == 1


# ------------------------------------------------------------------ command line


def run_cli(capsys, tmp_path, *extra):
    code = main(["graph", "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "idx"), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_overview(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path)
    assert code == 0
    assert "db.py::get_user -> db.py::validate_user_input" in out
    assert "nodes: 16" in out and "4 calls" in out


def test_cli_unit_shows_calls_and_callers(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "db.py::validate_user_input")
    assert code == 0
    assert "<- db.py::get_user" in out
    code, out, _ = run_cli(capsys, tmp_path, "db.py::get_user")
    assert "-> db.py::validate_user_input" in out and "(none)" in out


def test_cli_json_and_unknown_unit(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--json")
    assert code == 0 and len([e for e in json.loads(out)["edges"] if e["relation"] == "calls"]) == 4
    code, out, err = run_cli(capsys, tmp_path, "no_such_unit")
    assert code == 2 and "no unit matches" in err
    assert main(["graph", "--corpus", str(tmp_path / "missing")]) == 2


def test_partial_and_failed_units_from_tolerant_parsing():
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")
    fixture = Path(__file__).parent / "fixtures" / "tolerant_corpus"
    graph = build_graph(ingest_corpus(fixture, tolerant=True).units)
    statuses = {n.qualname: n.parse_status for n in graph.nodes.values()}
    assert statuses["Repo.half_broken"] == "partial" and statuses["header_broken"] == "failed"
    (edge,) = [e for e in graph.edges if e.relation == REL_CALLS]
    assert (edge.source, edge.target, edge.method) == (
        "broken_service.py::Repo.good_method", "broken_service.py::Repo.good_method", METHOD_SELF_METHOD)
    assert edge.line == _lines_containing(fixture / "broken_service.py", "self.good_method(x - 1)")[0]
    assert graph.edges_from("broken_service.py::header_broken") == []


def test_comprehension_variables_do_not_shadow_calls_elsewhere_in_the_unit(tmp_path):
    source = "def helper():\n    return 1\n\ndef f(xs):\n    ys = [helper for helper in xs]\n    return helper()\n"
    assert targets(make(tmp_path, {"a.py": source}), "a.py::f") == ["a.py::helper"]


def test_assignment_still_shadows_even_if_a_comprehension_reuses_the_name(tmp_path):
    source = "def helper():\n    return 1\n\ndef f(xs):\n    helper = len\n    ys = [helper for helper in xs]\n    return helper(xs)\n"
    assert targets(make(tmp_path, {"a.py": source}), "a.py::f") == []


def test_ensure_graph_rebuilds_when_the_marker_table_changes(tmp_path, monkeypatch):
    from structsearch.graph import store

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.py").write_text("def x(db):\n    return db.execute('q')\n")
    index = tmp_path / "idx"
    units = ingest_corpus(corpus).units
    _, reason = ensure_graph(units, index)
    assert reason == "no graph yet"
    assert ensure_graph(units, index)[1] is None
    monkeypatch.setattr(store, "markers_signature", lambda: "another marker table")
    assert ensure_graph(units, index)[1] == "units or markers changed"
