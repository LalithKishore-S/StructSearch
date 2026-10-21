import json
from pathlib import Path

import pytest

from structsearch.graph import (
    DEFAULT_MARKERS,
    METHOD_MARKER,
    REL_CALLS,
    REL_USES_API,
    CodeGraph,
    build_graph,
    describe_markers,
    match_markers,
)
from structsearch.ingestion import ingest_corpus
from structsearch.interface.cli import main

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def lines_of(path: Path, text: str):
    return [n for n, line in enumerate(path.read_text().split("\n"), 1) if text in line]


def make(tmp_path, source, name="m.py"):
    (tmp_path / name).write_text(source)
    return build_graph(ingest_corpus(tmp_path).units)


def markers(graph, unit_id):
    return [(e.target, e.line, e.detail) for e in graph.edges_from(unit_id, REL_USES_API)]


@pytest.fixture(scope="module")
def graph():
    return build_graph(ingest_corpus(CORPUS).units)


# ------------------------------------------------------------------ the sample corpus


def test_database_markers_on_the_sample_corpus(graph):
    db = CORPUS / "db.py"
    assert markers(graph, "db.py::get_user")[-1] == ("db:execute", lines_of(db, "db.execute(\"SELECT * FROM users WHERE name = ?\"")[0], "db.execute")
    assert markers(graph, "db.py::find_user_unsafe") == [("db:execute", lines_of(db, "db.execute(query)")[0], "db.execute")]
    assert markers(graph, "db.py::count_rows") == [("db:execute", lines_of(db, "db.execute(\"SELECT COUNT")[0], "db.execute")]
    assert graph.markers_of("db.py::validate_user_input") == []


def test_validation_marker_sits_on_the_validator_call(graph):
    line = lines_of(CORPUS / "db.py", "validate_user_input(username)")[0]
    assert ("validation:validate", line, "validate_user_input") in markers(graph, "db.py::get_user")
    # the corpus call edge and the marker edge describe the same call site
    (call,) = graph.edges_from("db.py::get_user", REL_CALLS)
    assert call.line == line and call.detail == "validate_user_input"


def test_validation_comes_before_execute_in_get_user_only(graph):
    def first(unit_id, label):
        return min(e.line for e in graph.markers_of(unit_id) if e.target == label)

    assert first("db.py::get_user", "validation:validate") < first("db.py::get_user", "db:execute")
    assert all(e.target != "validation:validate" for e in graph.markers_of("db.py::find_user_unsafe"))


def test_file_markers_on_the_sample_corpus(graph):
    for unit_id in ("files.py::read_config_safe", "files.py::write_log", "files.py::read_lines"):
        assert [e.target for e in graph.markers_of(unit_id)] == ["file:open"], unit_id
    assert [e.detail for e in graph.markers_of("files.py::read_lines")] == ["open"]


def test_units_without_markers(graph):
    for unit_id in ("trees.py::factorial", "trees.py::count_nodes", "utils.py::add", "utils.py::slugify",
                    "utils.py::Counter.increment", "trees.py::inorder_traverse"):
        assert graph.markers_of(unit_id) == [], unit_id


def test_units_with_marker_and_totals(graph):
    assert graph.units_with_marker("db:execute") == ["db.py::count_rows", "db.py::find_user_unsafe", "db.py::get_user"]
    assert graph.units_with_marker("file:open") == ["files.py::read_config_safe", "files.py::read_lines", "files.py::write_log"]
    assert graph.units_with_marker("nothing") == []
    assert len([e for e in graph.edges if e.relation == REL_CALLS]) == 4
    assert len([e for e in graph.edges if e.relation == REL_USES_API]) == 7


def test_marker_edges_use_the_marker_method(graph):
    assert {e.method for e in graph.edges if e.relation == REL_USES_API} == {METHOD_MARKER}


# ------------------------------------------------------------------ matching rules


def test_all_database_names_and_receivers(tmp_path):
    source = (
        "def run(conn, self_like):\n"
        "    cur = conn.cursor()\n"
        "    cur.execute('x')\n"
        "    cur.executemany('x', [])\n"
        "    cur.executescript('x')\n"
        "    self_like.db.execute('y')\n"
        "    conn.commit()\n"
    )
    graph = make(tmp_path, source)
    assert [(e.target, e.detail) for e in graph.markers_of("m.py::run")] == [
        ("db:cursor", "conn.cursor"), ("db:execute", "cur.execute"), ("db:execute", "cur.executemany"),
        ("db:execute", "cur.executescript"), ("db:execute", "self_like.db.execute"), ("db:commit", "conn.commit"),
    ]


def test_open_is_a_marker_only_as_a_plain_call(tmp_path):
    source = (
        "def a(p):\n    return open(p)\n\n"
        "def b(img):\n    return img.open()\n\n"
        "def c(open):\n    return open()\n\n"
        "def d():\n    open = len\n    return open([])\n"
    )
    graph = make(tmp_path, source)
    assert [e.target for e in graph.markers_of("m.py::a")] == ["file:open"]
    for unit_id in ("m.py::b", "m.py::c", "m.py::d"):
        assert graph.markers_of(unit_id) == [], unit_id


def test_corpus_function_named_like_a_marker_is_a_call_not_a_marker(tmp_path):
    source = "def open(path):\n    return path\n\ndef run():\n    return open('x')\n"
    graph = make(tmp_path, source)
    assert [e.target for e in graph.edges_from("m.py::run", REL_CALLS)] == ["m.py::open"]
    assert graph.markers_of("m.py::run") == []


def test_validation_names(tmp_path):
    names = ["validate", "validate_input", "is_valid", "sanitizeHtml", "sanitise", "verify_token",
             "check_password", "html.escape", "form.validate", "InputValidator"]
    body = "\n".join(f"    {n}(x)" if "." not in n else f"    {n}(x)" for n in names)
    graph = make(tmp_path, f"def run(x):\n{body}\n")
    labels = [e.target for e in graph.markers_of("m.py::run")]
    assert labels == ["validation:validate"] * len(names)


def test_names_that_only_contain_a_validation_word_are_not_markers(tmp_path):
    source = "def run(x):\n    checksum(x)\n    invalidate(x)\n    cleanup(x)\n    isinstance(x, str)\n    escalate(x)\n"
    graph = make(tmp_path, source)
    assert graph.markers_of("m.py::run") == []


def test_participles_and_unlisted_names_are_not_markers(tmp_path):
    graph = make(tmp_path, "def run(db):\n    db.execute_validated('x')\n    db.execute('y')\n")
    assert [e.target for e in graph.markers_of("m.py::run")] == ["db:execute"]  # only the second call


def test_marker_edges_are_sorted_with_call_edges_by_line(tmp_path):
    source = "def check(x):\n    return x\n\ndef run(db, x):\n    check(x)\n    db.execute('z')\n"
    graph = make(tmp_path, source)
    assert [(e.relation, e.target, e.line) for e in graph.edges_from("m.py::run")] == [
        (REL_CALLS, "m.py::check", 5), (REL_USES_API, "validation:validate", 5), (REL_USES_API, "db:execute", 6),
    ]


def test_calls_in_nested_functions_count_for_the_unit(tmp_path):
    graph = make(tmp_path, "def run(db):\n    def inner():\n        db.execute('x')\n    return inner\n")
    assert [e.target for e in graph.markers_of("m.py::run")] == ["db:execute"]


def test_failed_units_have_no_markers(tmp_path):
    graph = make(tmp_path, "def broken(:\n    db.execute('x')\n")
    assert graph.edges == []


# ------------------------------------------------------------------ marker table


def test_marker_table_is_small_and_documented():
    labels = [m.label for m in DEFAULT_MARKERS]
    assert len(labels) == len(set(labels)) and 4 <= len(labels) <= 8
    assert all(m.description and m.category in ("db", "file", "validation") for m in DEFAULT_MARKERS)
    rows = describe_markers()
    assert {r["label"] for r in rows} == set(labels)


def test_match_markers_with_a_custom_table(tmp_path):
    import ast

    from structsearch.graph import Marker

    table = (Marker("net:request", "db", "HTTP request", attr_names=("get", "post")),)
    call = ast.parse("session.get(url)").body[0].value
    assert [m.label for m, _ in match_markers(call, set(), table)] == ["net:request"]
    assert match_markers(call, set(), ()) == []
    graph = make(tmp_path, "def run(session, url):\n    return session.post(url)\n")
    custom = build_graph(ingest_corpus(tmp_path).units, markers=table)
    assert [e.target for e in custom.markers_of("m.py::run")] == ["net:request"]
    assert graph.markers_of("m.py::run") == []


# ------------------------------------------------------------------ persistence and CLI


def test_round_trip_keeps_markers_and_details(graph):
    restored = CodeGraph.from_dict(json.loads(json.dumps(graph.to_dict())))
    assert restored.to_dict() == graph.to_dict()
    assert restored.markers_of("db.py::get_user") == graph.markers_of("db.py::get_user")


def run_cli(capsys, tmp_path, *extra):
    code = main(["graph", "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "idx"), *extra])
    out = capsys.readouterr()
    return code, out.out


def test_cli_shows_markers_for_a_unit_and_in_the_summary(capsys, tmp_path):
    code, out = run_cli(capsys, tmp_path, "db.py::get_user")
    assert code == 0 and "-> db:execute" in out and "-> validation:validate" in out and "db.execute" in out
    code, out = run_cli(capsys, tmp_path)
    assert "edges: 11 (4 calls, 7 uses_api)" in out


def test_cli_markers_table(capsys, tmp_path):
    code, out = run_cli(capsys, tmp_path, "--markers")
    assert code == 0
    for marker in DEFAULT_MARKERS:
        assert marker.label in out
