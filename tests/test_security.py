import json
from pathlib import Path

import pytest

from structsearch.graph import build_graph
from structsearch.ingestion import ingest_corpus
from structsearch.interface.cli import main
from structsearch.security import (
    DISCLAIMER,
    NOT_MODELLED,
    PATTERN_QUERY,
    candidates_to_results,
    level_of,
    scan_sql_candidates,
)

ROOT = Path(__file__).parent.parent
CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"
DEMO = ROOT / "experiments" / "security_demo"


def line_of(text, path=DEMO / "app.py"):
    """1-based line of the only line of `path` that contains `text`."""
    hits = [n for n, line in enumerate(path.read_text().split("\n"), 1) if text in line]
    assert len(hits) == 1, (text, hits)
    return hits[0]


def scan(path):
    units = ingest_corpus(path).units
    return {c.unit_id: c for c in scan_sql_candidates(units, build_graph(units))}, units


def scan_source(tmp_path, source):
    (tmp_path / "m.py").write_text(source)
    found, _ = scan(tmp_path)
    return found


@pytest.fixture(scope="module")
def sample():
    return scan(CORPUS)[0]


@pytest.fixture(scope="module")
def demo():
    return scan(DEMO)[0]


# ------------------------------------------------------------------ the sample corpus


def test_sample_corpus_candidates(sample):
    assert set(sample) == {"db.py::find_user_unsafe", "db.py::count_rows"}
    assert all(c.level == "high" and c.score == pytest.approx(0.8) for c in sample.values())


def test_parameterized_and_validating_functions_are_not_candidates(sample):
    assert "db.py::get_user" not in sample and "db.py::validate_user_input" not in sample


def test_evidence_is_factual_and_ends_with_the_disclaimer(sample):
    assert sample["db.py::find_user_unsafe"].evidence == [
        "level: high (score 0.80)",
        "source: parameter 'username' of find_user_unsafe",
        "construction: string concatenation at line 18 uses 'username'",
        "sink: db:execute at line 19 (db.execute) receives the built text via variable 'query'",
        "validation: no validation step before the query",
        DISCLAIMER,
    ]
    assert sample["db.py::count_rows"].evidence[1:5] == [
        "source: parameter 'table_name' of count_rows",
        "construction: string concatenation at line 24 uses 'table_name'",
        "sink: db:execute at line 24 (db.execute) receives the built text directly",
        "validation: no validation step before the query",
    ]


def test_sample_candidates_match_the_benchmark_judgement(sample):
    from structsearch.evaluation import read_records

    relevant = {r["unit_id"] for r in read_records(ROOT / "experiments/benchmark/labels.jsonl")
                if r["query_id"] == "R13" and int(r["relevance"]) > 0}
    assert set(sample) == relevant


# ------------------------------------------------------------------ the demo module


def test_demo_candidates_and_scores(demo):
    got = {u.split("::")[1]: (c.level, round(c.score, 3)) for u, c in demo.items()}
    assert got == {
        "search_by_name": ("high", 1.0),
        "cli_lookup": ("high", 1.0),
        "search_fstring": ("high", 0.8),
        "search_format": ("high", 0.8),
        "search_percent": ("high", 0.8),
        "lookup": ("medium", 0.56),
        "run_query": ("medium", 0.48),
        "search_validated_first": ("medium", 0.4),
        "endpoint": ("medium", 0.392),
        "handler": ("low", 0.336),
        "search_validated_value": ("low", 0.24),
    }


def test_demo_functions_that_are_left_out(demo):
    names = {u.split("::")[1] for u in demo}
    assert {"search_parameterized", "constant_query", "validate_name"}.isdisjoint(names)


def test_external_sources_are_named(demo):
    ev = demo["app.py::search_by_name"].evidence
    assert f"source: external input request.args.get (line {line_of('request.args.get')})" in ev
    sink = line_of("request.args.get") + 2  # name = ...; sql = ...; return db.execute(sql)
    assert f"sink: db:execute at line {sink} (db.execute) receives the built text via variable 'sql'" in ev
    assert f"source: external input input() (line {line_of('input(\"name: \")')})" in demo["app.py::cli_lookup"].evidence


def test_construction_kinds(demo):
    def construction(name):
        return next(l for l in demo[f"app.py::{name}"].evidence if l.startswith("construction:"))

    assert "f-string" in construction("search_fstring")
    assert ".format()" in construction("search_format")
    assert "% formatting" in construction("search_percent")
    assert "concatenation" in construction("search_by_name")


def test_validation_notes(demo):
    first = demo["app.py::search_validated_first"].evidence
    assert any(l.startswith("validation: validation step at line") and "precedes the query" in l
               and "effectiveness not assessed" in l for l in first)
    value = demo["app.py::search_validated_value"].evidence
    assert any("passed through validate_name at line" in l and "effectiveness not assessed" in l for l in value)
    assert any(l == "validation: no validation step before the query" for l in demo["app.py::search_fstring"].evidence)


def test_paths_through_callers(demo):
    assert any(l.startswith("path: lookup -> search_percent (call, line") for l in demo["app.py::lookup"].evidence)
    ev = demo["app.py::endpoint"].evidence
    assert [l for l in ev if l.startswith("path:")] == [
        f"path: endpoint -> lookup (call, line {line_of('return lookup(db, text)')})",
        f"path: lookup -> search_percent (call, line {line_of('return search_percent(db, user)')})",
    ]
    assert demo["app.py::endpoint"].hops == 2 and demo["app.py::lookup"].hops == 1
    assert demo["app.py::handler"].hops == 1 and demo["app.py::search_percent"].hops == 0
    assert any(l.startswith("sink: db:execute") and "parameter 'sql' directly" in l for l in demo["app.py::handler"].evidence)


def test_run_query_executes_its_parameter_directly(demo):
    ev = demo["app.py::run_query"].evidence
    assert any("receives parameter 'sql' directly" in l for l in ev)
    assert not any(l.startswith("construction:") for l in ev)


def test_results_are_ranked_by_score_then_unit_id(demo):
    units = ingest_corpus(DEMO).units
    ranked = scan_sql_candidates(units, build_graph(units))
    assert [c.score for c in ranked] == sorted((c.score for c in ranked), reverse=True)
    top = [c.unit_id for c in ranked[:2]]
    assert top == ["app.py::cli_lookup", "app.py::search_by_name"]


# ------------------------------------------------------------------ rules at the edges


def test_sql_keyword_is_required(tmp_path):
    found = scan_source(tmp_path, "def f(db, a):\n    return db.execute('hello ' + a)\n")
    assert found == {}


def test_derived_locals_carry_the_source(tmp_path):
    src = ("def f(db, a):\n    b = a.strip()\n    c = b.lower()\n"
           "    return db.execute('SELECT x FROM t WHERE y = ' + c)\n")
    (c,) = scan_source(tmp_path, src).values()
    assert "source: parameter 'a' of f" in c.evidence


def test_augmented_assignment_builds_sql(tmp_path):
    src = ("def f(db, a):\n    q = 'SELECT x FROM t WHERE y = '\n    q += a\n    return db.execute(q)\n")
    (c,) = scan_source(tmp_path, src).values()
    assert any(l.startswith("construction: string concatenation at line 3") for l in c.evidence)


def test_reassigned_clean_value_clears_the_source(tmp_path):
    src = ("def f(db, a):\n    a = 'fixed'\n    return db.execute('SELECT x FROM t WHERE y = ' + a)\n")
    assert scan_source(tmp_path, src) == {}


def test_methods_skip_self(tmp_path):
    src = ("class R:\n    def f(self, db, a):\n        return db.execute('SELECT x FROM t WHERE y = ' + a)\n")
    (c,) = scan_source(tmp_path, src).values()
    assert c.unit_id == "m.py::R.f" and "source: parameter 'a' of R.f" in c.evidence


def test_keyword_and_method_arguments_in_paths(tmp_path):
    src = ("def run(db, sql):\n    return db.execute(sql)\n\n"
           "def top(db, text):\n    return run(db=db, sql=text)\n")
    found = scan_source(tmp_path, src)
    assert set(found) == {"m.py::run", "m.py::top"} and found["m.py::top"].hops == 1


def test_path_needs_the_argument_to_carry_input(tmp_path):
    src = ("def run(db, sql):\n    return db.execute(sql)\n\n"
           "def top(db):\n    return run(db, 'SELECT 1')\n")
    assert set(scan_source(tmp_path, src)) == {"m.py::run"}


def test_validation_before_a_call_lowers_the_path_score(tmp_path):
    src = ("def run(db, sql):\n    return db.execute(sql)\n\n"
           "def plain(db, text):\n    return run(db, text)\n\n"
           "def checked(db, text):\n    check_input(text)\n    return run(db, text)\n")
    found = scan_source(tmp_path, src)
    assert found["m.py::checked"].score == pytest.approx(found["m.py::plain"].score * 0.5)


def test_failed_units_are_ignored(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n")
    (tmp_path / "ok.py").write_text("def f(db, a):\n    return db.execute('SELECT x FROM t WHERE y = ' + a)\n")
    found, _ = scan(tmp_path)
    assert set(found) == {"ok.py::f"}


def test_levels():
    assert [level_of(s) for s in (1.0, 0.7, 0.69, 0.35, 0.34, 0.01)] == ["high", "high", "medium", "medium", "low", "low"]


def test_documentation_constants():
    assert "candidate" in DISCLAIMER and "not confirmed" in DISCLAIMER
    assert len(NOT_MODELLED) >= 6 and "external input" in PATTERN_QUERY
    for banned in ("vulnerable", "exploit", "confirmed vulnerab"):
        assert banned not in DISCLAIMER.lower()


# ------------------------------------------------------------------ ranked results and CLI


def test_candidates_as_ranked_results():
    units = ingest_corpus(CORPUS).units
    results = candidates_to_results(scan_sql_candidates(units, build_graph(units)), "sec")
    assert [r.unit_id for r in results] == ["db.py::count_rows", "db.py::find_user_unsafe"]
    top = results[0]
    assert (top.query_id, top.text_score, top.structural_score) == ("sec", 0.0, 0.0)
    assert top.graph_score == top.final_score == pytest.approx(0.8) and top.evidence[0].startswith("level: high")


def run_cli(capsys, tmp_path, *args, corpus=CORPUS):
    code = main(["security", "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx"), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_text_output(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--lines", "0")
    assert code == 0 and DISCLAIMER in out and "db.py::find_user_unsafe" in out and "db.py::count_rows" in out
    assert "vulnerable" not in out.lower().replace("not confirmed vulnerabilities", "")


def test_cli_json_and_limit(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--json", "-k", "1")
    payload = json.loads(out)
    assert code == 0 and payload["disclaimer"] == DISCLAIMER and payload["pattern"] == PATTERN_QUERY
    assert len(payload["results"]) == 1 and payload["results"][0]["level"] == "high"
    assert payload["not_modelled"] == NOT_MODELLED


def test_cli_demo_module_and_min_level(capsys, tmp_path):
    code, out, _ = run_cli(capsys, tmp_path, "--json", "-k", "50", corpus=DEMO)
    assert len(json.loads(out)["results"]) == 11
    code, out, _ = run_cli(capsys, tmp_path, "--json", "-k", "50", "--min-level", "high", corpus=DEMO)
    assert {r["level"] for r in json.loads(out)["results"]} == {"high"}


def test_cli_no_candidates_and_missing_corpus(capsys, tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.py").write_text("def f(x):\n    return x\n")
    code, out, _ = run_cli(capsys, tmp_path, corpus=clean)
    assert code == 0 and "No candidates" in out
    assert main(["security", "--corpus", str(tmp_path / "missing")]) == 2
