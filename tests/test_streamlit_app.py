"""The Streamlit page, driven without a browser through Streamlit's AppTest."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from structsearch.interface.service import SearchError
from structsearch.interface.streamlit_app import run_ui_search, scan_corpus_candidates, search_rows
from structsearch.interface.ui_data import DEMO_QUERIES

ROOT = Path(__file__).parent.parent
APP = str(ROOT / "structsearch" / "interface" / "streamlit_app.py")
CORPUS = str(Path(__file__).parent / "fixtures" / "sample_corpus")


def app(tmp_path):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["corpus"] = CORPUS
    at.session_state["index_dir"] = str(tmp_path / "idx")
    return at.run()


def texts(at):
    out = [m.value for m in at.markdown] + [m.value for m in at.caption] + [e.value for e in at.error]
    out += [e.value for e in at.success] + [e.value for e in at.warning] + [e.value for e in at.info]
    out += [h.value for h in at.subheader]
    return "\n".join(str(t) for t in out)


# ------------------------------------------------------------------ data functions behind the page


def test_ui_search_bundle(tmp_path):
    ui = run_ui_search("validate user input before database access", "text_ast_graph", 3, CORPUS, str(tmp_path / "i"))
    assert [r.unit_id for r in ui.response.results][0] == "db.py::get_user"
    assert ui.understanding["intents"][0]["name"] == "validated_db" and ui.breakdown[0]["name"] == "get_user"
    assert len(ui.rows) == 3 and "explanation" in ui.rows[0] and len(ui.graph.nodes) == 16


def test_ui_search_options(tmp_path):
    ui = run_ui_search("tree", "text_graph", 5, CORPUS, str(tmp_path / "i"), explain="none", intents=["recursive"],
                       weights=["text=0", "graph=1"])
    assert ui.understanding["weights"] == {"graph": 1.0} and "explanation" not in ui.rows[0]
    assert {r.unit_id for r in ui.response.results} == {"trees.py::factorial", "trees.py::inorder_traverse"}
    with pytest.raises(SearchError):
        run_ui_search("tree", "text_graph", 5, CORPUS, str(tmp_path / "i"), intents=["telepathy"])


def test_security_scan_data(tmp_path):
    candidates, units, graph = scan_corpus_candidates(CORPUS, str(tmp_path / "i"))
    assert [c.unit_id for c in candidates] == ["db.py::count_rows", "db.py::find_user_unsafe"] and len(graph.nodes) == 16


def test_search_rows_helper_still_works(tmp_path):
    data = search_rows("recursive tree traversal", "text_ast", 3, CORPUS, str(tmp_path / "i"), "template", False, [])
    assert data["rows"][0]["unit_id"] == "trees.py::inorder_traverse"


# ------------------------------------------------------------------ the page


def test_page_opens_with_the_best_mode_and_a_hint(tmp_path):
    at = app(tmp_path)
    assert not at.exception
    assert "text_ast_graph" in "".join(c.value for c in at.sidebar.caption)
    assert "Type a query" in texts(at)
    assert [t.label for t in at.tabs] == ["Search", "Security candidates", "Call graph", "Results"]


def test_searching_shows_understanding_breakdown_graph_and_results(tmp_path):
    at = app(tmp_path)
    at.text_input(key="query").set_value("validate user input before database access").run()
    assert not at.exception
    body = texts(at)
    assert "validated_db" in body and "1. How the query was understood" in body and "3. Evidence graph" in body
    assert "validation words" in body and "`validate`" in body
    graphs = at.get("graphviz_chart")
    assert len(graphs) >= 2  # evidence graph in the Search tab and the whole graph in the Call graph tab
    assert "db:execute" in str(graphs[0].proto.spec) and "line 12" in str(graphs[0].proto.spec)
    assert at.get("arrow_vega_lite_chart") or at.get("vega_lite_chart") or at.get("arrow_chart")


def test_example_query_shows_the_expected_answer_and_checks_it(tmp_path):
    at = app(tmp_path)
    at.selectbox(key="example").select(DEMO_QUERIES[0]["label"]).run()
    assert at.session_state["query"] == DEMO_QUERIES[0]["query"]
    body = texts(at)
    assert "Expected top answers" in body and "find_user_unsafe" in body
    assert any("matches the expectation" in s.value for s in at.success)


def test_known_limitation_example_is_flagged_not_hidden(tmp_path):
    limit = next(d for d in DEMO_QUERIES if d["kind"] == "limit")
    at = app(tmp_path)
    at.selectbox(key="example").select(limit["label"]).run()
    assert not at.exception and any("documented failure" in w.value for w in at.warning)


def test_empty_example_returns_nothing(tmp_path):
    empty = next(d for d in DEMO_QUERIES if d["kind"] == "empty")
    at = app(tmp_path)
    at.selectbox(key="example").select(empty["label"]).run()
    assert not at.exception and any("Nothing returned" in s.value for s in at.success)


def test_sidebar_is_simple(tmp_path):
    at = app(tmp_path)
    assert [s.key for s in at.sidebar.selectbox] == ["example"]
    assert not at.sidebar.multiselect and not at.sidebar.checkbox and not at.sidebar.expander
    assert {t.key for t in at.sidebar.text_input} == {"corpus", "index_dir"}


def test_graph_mode_note_for_a_query_without_relationship(tmp_path):
    at = app(tmp_path)
    at.text_input(key="query").set_value("convert camel case name to snake case").run()
    assert not at.exception and "left out" in texts(at)


def test_a_bad_corpus_shows_an_error_not_a_crash(tmp_path):
    at = app(tmp_path)
    at.session_state["corpus"] = str(tmp_path / "missing")
    at.text_input(key="query").set_value("anything").run()
    assert not at.exception and any("corpus path not found" in e.value for e in at.error)


def test_security_tab_lists_the_candidates_with_the_disclaimer(tmp_path):
    at = app(tmp_path)
    body = texts(at)
    assert "not confirmed" in body and "possible paths from external input" in body
    rows = at.dataframe[0].value
    assert list(rows["function"]) == ["db.py::count_rows", "db.py::find_user_unsafe"]
    assert all(level == "high" for level in rows["level"])


def test_call_graph_tab_renders_and_inspects_a_function(tmp_path):
    at = app(tmp_path)
    at.selectbox(key="graph_unit").select("db.py::get_user").run()
    assert not at.exception
    body = texts(at)
    assert "db.py::validate_user_input" in body and "`db:execute` (line 13)" in body
    at.selectbox(key="graph_file").select("trees.py").run()
    assert not at.exception


def test_every_example_label_is_selectable(tmp_path):
    at = app(tmp_path)
    options = list(at.selectbox(key="example").options)
    assert options[0] == "(none)" and len(options) == len(DEMO_QUERIES) + 1


# ------------------------------------------------------------------ the Results tab


def chart_count(at):
    return len(at.get("arrow_vega_lite_chart")) + len(at.get("vega_lite_chart")) + len(at.get("arrow_chart"))


def table_rows(at, first_column):
    for frame in at.dataframe:
        df = frame.value
        if first_column in df.columns:
            return df
    raise AssertionError(f"no table with column {first_column}")


def test_results_tab_defaults_to_the_test_split(tmp_path):
    at = app(tmp_path)
    assert not at.exception
    body = texts(at)
    assert "Test split" in body and "run once" in body and "frozen benchmark" in body
    assert "1. Variants compared (14 queries)" in body
    assert chart_count(at) >= 2  # variants and ablation
    variants = table_rows(at, "variant")
    full = variants[variants["variant"] == "Full (Text + AST + Graph)"].iloc[0]
    base = variants[variants["variant"] == "BM25 (baseline)"].iloc[0]
    assert full["nDCG@K"] == pytest.approx(0.952, abs=1e-3) and base["nDCG@K"] == pytest.approx(0.787, abs=1e-3)


def test_results_tab_development_split_is_marked_optimistic(tmp_path):
    at = app(tmp_path)
    at.radio(key="res_split").set_value("Development split").run()
    assert not at.exception
    body = texts(at)
    assert "optimistic" in body and "(20 queries)" in body


def test_results_tab_controls_and_relationship_view(tmp_path):
    at = app(tmp_path)
    at.select_slider(key="res_k").set_value(1).run()
    assert not at.exception
    at.selectbox(key="res_category").select("Relationship").run()
    assert not at.exception and "(8 queries)" in texts(at)
    at.selectbox(key="res_metric").select("MRR").run()
    assert not at.exception
    paired = table_rows(at, "better")
    full = paired[paired["variant"] == "Full (Text + AST + Graph)"].iloc[0]
    assert (full["queries"], full["better"], full["same"], full["worse"]) == (8, 2, 6, 0)  # K = 1, from paired.csv


def test_results_tab_lists_what_improved_and_what_did_not(tmp_path):
    at = app(tmp_path)
    body = "\n".join(m.value for m in at.markdown)
    assert "**R17** opening files without catching exceptions" in body and "**L12**" in body
    assert "rank none with BM25" in body


def test_results_tab_query_inspector(tmp_path):
    at = app(tmp_path)
    at.selectbox(key="result_query").select("R17").run()
    assert not at.exception
    body = texts(at)
    assert "opening files without catching exceptions" in body and "`read_lines`" in body and "`write_log`" in body
    detail = table_rows(at, "first correct at rank")
    bm25 = detail[detail["variant"] == "BM25 (baseline)"].iloc[0]
    full = detail[detail["variant"] == "Full (Text + AST + Graph)"].iloc[0]
    assert bm25["first correct at rank"] == "-" and full["first correct at rank"] == "2"
    assert full["rank 2"].startswith("[correct]")


def test_results_tab_without_a_run_explains_how_to_make_one(tmp_path, monkeypatch):
    from structsearch.interface import results_data

    monkeypatch.setattr(results_data, "DEFAULT_RUN", tmp_path / "nothing")
    at = app(tmp_path)
    assert not at.exception and any("No experiment results found" in i.value for i in at.info)
