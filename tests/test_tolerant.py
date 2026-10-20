import json
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_python")

from structsearch.ingestion import ingest_corpus
from structsearch.ingestion.repair import repair_source
from structsearch.ingestion.segmenter import split_source
from structsearch.indexing.builder import ensure_index
from structsearch.interface.cli import main
from structsearch.parsing import extract_features, extract_fragments
from structsearch.parsing.tolerant import TolerantUnavailable, tolerant_split
from structsearch.schemas import CodeUnit, status_flag

FIX = Path(__file__).parent / "fixtures" / "tolerant_corpus"
SRC = (FIX / "broken_service.py").read_text()


@pytest.fixture(scope="module")
def units():
    got, errors = tolerant_split(SRC, "broken_service.py")
    return {u.unit_id: u for u in got}, errors


def test_functions_recovered_with_statuses(units):
    by_id, errors = units
    assert set(by_id) == {
        "broken_service.py::Repo.good_method", "broken_service.py::Repo.half_broken",
        "broken_service.py::Repo.unclosed", "broken_service.py::after_everything",
        "broken_service.py::header_broken",
    }
    status = {k.split("::")[1]: v.parse_status for k, v in by_id.items()}
    assert status == {"Repo.good_method": "ok", "Repo.half_broken": "partial", "Repo.unclosed": "partial",
                      "after_everything": "ok", "header_broken": "failed"}
    assert 14 in errors and 20 in errors


def test_error_lines_are_absolute_file_lines(units):
    by_id, _ = units
    half = by_id["broken_service.py::Repo.half_broken"]
    assert half.error_lines == [14] and SRC.split("\n")[13].strip().startswith("total += row ???")
    assert (half.start_line, half.end_line) == (11, 17)
    assert by_id["broken_service.py::Repo.good_method"].error_lines == []


def test_spans_match_file_lines(units):
    by_id, _ = units
    lines = SRC.split("\n")
    for u in by_id.values():
        assert u.source_text == "\n".join(lines[u.start_line - 1 : u.end_line])


def test_valid_function_matches_normal_pipeline(units):
    by_id, _ = units
    tolerant = by_id["broken_service.py::after_everything"]
    clean = split_source(tolerant.source_text, "broken_service.py")[0]
    assert extract_features(tolerant).features == extract_features(clean).features
    assert extract_fragments(tolerant).terms == extract_fragments(clean).terms


def test_partial_unit_has_features_from_the_good_lines(units):
    by_id, _ = units
    rec = extract_features(by_id["broken_service.py::Repo.half_broken"])
    assert rec.parse_status == "partial"
    assert rec.features["for_count"] == 1 and rec.features["if_count"] == 1
    frag = extract_fragments(by_id["broken_service.py::Repo.half_broken"])
    assert frag.parse_status == "partial" and "ad:For//If" in frag.terms


def test_failed_function_has_no_features(units):
    by_id, _ = units
    assert extract_features(by_id["broken_service.py::header_broken"]).parse_status == "failed"


def test_repair_only_removes_lines():
    text = "def f(x):\n    a = 1 ???\n    for i in x:\n        pass\n    return a"
    fixed, edited = repair_source(text)
    assert edited == [2] and fixed.split("\n")[1].strip() == "pass"
    assert fixed.split("\n")[2:] == text.split("\n")[2:]
    assert repair_source("def f(x:\n    return x") is None
    assert repair_source("x = 1") is None


def test_defs_inside_strings_nested_and_decorators():
    src = (
        'def outer(a):\n    """\ndef fake():\n    pass\n"""\n    def inner():\n        return a\n    return inner(\n\n'
        "@deco\nasync def later(b):\n    await b\n\nclass K:\n    def m(self):\n        return 1 +\n"
    )
    got, _ = tolerant_split(src, "m.py")
    ids = [u.unit_id for u in got]
    assert ids == ["m.py::outer", "m.py::later", "m.py::K.m"]
    later = got[1]
    assert later.source_text.startswith("@deco\nasync def later")


def test_duplicate_names_numbered():
    got, _ = tolerant_split("def f():\n    return 1 +\ndef f():\n    return 2 +\n", "d.py")
    assert [u.unit_id for u in got] == ["d.py::f", "d.py::f#2"]


def test_valid_file_is_not_changed_by_tolerant_flag():
    plain = ingest_corpus(Path(__file__).parent / "fixtures" / "sample_corpus")
    tol = ingest_corpus(Path(__file__).parent / "fixtures" / "sample_corpus", tolerant=True)
    ok_plain = [u.to_dict() for u in plain.units if u.file_path != "broken_syntax.py"]
    ok_tol = [u.to_dict() for u in tol.units if u.file_path != "broken_syntax.py"]
    assert ok_plain == ok_tol


def test_ingest_default_keeps_file_unit_and_tolerant_splits():
    default = ingest_corpus(FIX)
    assert [u.unit_id for u in default.units] == ["broken_service.py::<module>"]
    tol = ingest_corpus(FIX, tolerant=True)
    assert len(tol.units) == 5
    failed = tol.failed_files[0]
    assert failed.recovered_units == 5 and 14 in failed.error_lines


def test_file_with_nothing_recoverable_falls_back(tmp_path):
    (tmp_path / "junk.py").write_text("x = (\ny = ???\n")
    res = ingest_corpus(tmp_path, tolerant=True)
    assert [u.unit_id for u in res.units] == ["junk.py::<module>"]


def test_unavailable_raises(monkeypatch):
    import structsearch.parsing.tolerant as tol

    monkeypatch.setattr(tol, "_PARSER", None)
    monkeypatch.setitem(__import__("sys").modules, "tree_sitter_python", None)
    with pytest.raises(TolerantUnavailable) as exc:
        ingest_corpus(FIX, tolerant=True)
    assert "pip install" in str(exc.value)


def test_index_rebuilds_when_tolerant_setting_changes(tmp_path):
    idx = tmp_path / "i"
    units, _, reason = ensure_index(FIX, idx)
    assert reason == "no index yet" and len(units) == 1
    units, _, reason = ensure_index(FIX, idx, tolerant=True)
    assert reason == "tolerant-parsing setting changed" and len(units) == 5
    _, _, reason = ensure_index(FIX, idx, tolerant=True)
    assert reason is None


def test_status_flag_and_old_records():
    u = CodeUnit("a::f", "a.py", 1, 2, "f", "x", parse_status="partial", error_lines=[3, 4])
    assert status_flag(u) == "  [partial parse: syntax errors at line 3, 4]"
    old = {"unit_id": "a::f", "file_path": "a.py", "start_line": 1, "end_line": 2, "name": "f", "source_text": "x"}
    assert CodeUnit.from_dict(old).error_lines == []


def test_cli_search_tolerant(tmp_path, capsys):
    args = ["search", "loop", "--mode", "text_ast", "--corpus", str(FIX), "--index-dir", str(tmp_path / "i"), "--tolerant"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "[partial parse: syntax errors at line 14]" in out
    assert main(args + ["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    half = next(r for r in data["results"] if r["unit_id"].endswith("half_broken"))
    assert half["parse_status"] == "partial" and half["structural_score"] >= 0
    assert any(e.startswith("partial parse") for e in half["evidence"])


def test_cli_search_tolerant_missing_dependency(tmp_path, capsys, monkeypatch):
    import structsearch.parsing.tolerant as tol

    monkeypatch.setattr(tol, "_PARSER", None)
    monkeypatch.setitem(__import__("sys").modules, "tree_sitter_python", None)
    code = main(["search", "x", "--corpus", str(FIX), "--index-dir", str(tmp_path / "i"), "--tolerant"])
    assert code == 2 and "tree-sitter" in capsys.readouterr().err


def test_cli_ingestion_reports_error_regions(tmp_path, capsys):
    from structsearch.ingestion.cli import main as ingest_main

    assert ingest_main([str(FIX), "--tolerant", "--out", str(tmp_path / "u.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "recovered 5 function(s); syntax errors at lines" in out
