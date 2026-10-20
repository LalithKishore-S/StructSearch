import json
import re
from pathlib import Path

from structsearch.ingestion import (
    fingerprint_units,
    ingest_corpus,
    load_failed,
    load_units,
    parse_unit,
    save_failed,
    save_units,
    split_source,
)
from structsearch.ingestion.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "sample_corpus"


def _ids(source, path="m.py"):
    return [u.unit_id for u in split_source(source, path)]


# ---- fixture corpus (acceptance test) ----

def test_fixture_units_match_manifest():
    manifest = json.loads((FIXTURES / "expected_units.json").read_text())
    result = ingest_corpus(CORPUS)
    expected = manifest["units"] + manifest["failed_units"]
    assert sorted(u.unit_id for u in result.units) == sorted(expected)
    assert result.files_scanned == 5
    assert [f.rel_path for f in result.failed_files] == manifest["unparseable_files"]
    assert "SyntaxError" in result.failed_files[0].error
    # The exact line depends on the Python version (3.13 reports 1, older versions 2).
    assert result.failed_files[0].line in (1, 2)


def test_skip_failed_keeps_only_function_units():
    manifest = json.loads((FIXTURES / "expected_units.json").read_text())
    result = ingest_corpus(CORPUS, include_failed=False)
    assert sorted(u.unit_id for u in result.units) == sorted(manifest["units"])
    assert len(result.failed_files) == 1


def test_failed_file_becomes_file_level_unit():
    units = {u.unit_id: u for u in ingest_corpus(CORPUS).units}
    unit = units["broken_syntax.py::<module>"]
    assert unit.parse_status == "failed" and unit.language == "python"
    assert unit.name == "broken_syntax"
    assert (unit.start_line, unit.end_line) == (1, 2)
    assert unit.source_text == "def broken_function(x:\n    return x +"


def test_unit_ids_unique_and_deterministic():
    first = ingest_corpus(CORPUS)
    second = ingest_corpus(CORPUS)
    ids = [u.unit_id for u in first.units]
    assert len(ids) == len(set(ids))
    assert ids == [u.unit_id for u in second.units]


def test_known_line_ranges():
    units = {u.unit_id: u for u in ingest_corpus(CORPUS).units}
    fact = units["trees.py::factorial"]
    assert (fact.start_line, fact.end_line) == (17, 21)
    assert fact.name == "factorial"
    assert fact.source_text.startswith("def factorial(n):")
    method = units["utils.py::Counter.increment"]
    assert (method.start_line, method.end_line) == (21, 24)
    assert method.source_text.startswith("    def increment")


def test_source_text_is_exact_file_slice():
    for unit in ingest_corpus(CORPUS).units:
        lines = (CORPUS / unit.file_path).read_text().split("\n")
        assert unit.source_text == "\n".join(lines[unit.start_line - 1 : unit.end_line])


def test_function_units_ok_and_python():
    for unit in ingest_corpus(CORPUS).units:
        expected = "failed" if unit.unit_id.endswith("::<module>") else "ok"
        assert unit.parse_status == expected and unit.language == "python"


def test_parse_unit_handles_methods_and_functions():
    units = {u.unit_id: u for u in ingest_corpus(CORPUS).units}
    assert parse_unit(units["utils.py::Counter.increment"]).name == "increment"
    assert parse_unit(units["trees.py::factorial"]).name == "factorial"


# ---- segmentation edge cases ----

def test_nested_function_is_not_separate_unit():
    src = "def outer():\n    def inner():\n        pass\n    return inner\n"
    assert _ids(src) == ["m.py::outer"]


def test_nested_classes_and_async():
    src = (
        "class A:\n"
        "    class B:\n"
        "        def m(self):\n"
        "            pass\n"
        "    async def run(self):\n"
        "        pass\n"
    )
    assert _ids(src) == ["m.py::A.B.m", "m.py::A.run"]


def test_decorators_included_in_range():
    src = "import functools\n\n@functools.lru_cache\n@staticmethod\ndef f():\n    pass\n"
    unit = split_source(src, "m.py")[0]
    assert unit.start_line == 3 and unit.end_line == 6
    assert unit.source_text.startswith("@functools.lru_cache")
    assert parse_unit(unit).name == "f"


def test_duplicate_names_get_suffix():
    src = (
        "class A:\n"
        "    @property\n"
        "    def x(self):\n"
        "        return 1\n"
        "    @x.setter\n"
        "    def x(self, v):\n"
        "        pass\n"
    )
    assert _ids(src) == ["m.py::A.x", "m.py::A.x#2"]


def test_functions_under_if_try_are_found():
    src = (
        "try:\n"
        "    import fast\n"
        "    def f():\n"
        "        pass\n"
        "except ImportError:\n"
        "    def f():\n"
        "        pass\n"
    )
    assert _ids(src) == ["m.py::f", "m.py::f#2"]


def test_form_feed_does_not_shift_lines():
    src = "def a():\n    pass\n\x0c\ndef b():\n    return 1\n"
    units = {u.name: u for u in split_source(src, "m.py")}
    assert units["b"].start_line == 4
    assert units["b"].source_text == "def b():\n    return 1"


def test_crlf_source():
    src = "def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n"
    units = {u.name: u for u in split_source(src, "m.py")}
    assert units["b"].source_text == "def b():\n    return 2"
    assert (units["b"].start_line, units["b"].end_line) == (4, 5)


def test_method_with_column0_string_still_parses():
    src = 'class A:\n    def m(self):\n        return """\nraw\n"""\n'
    unit = split_source(src, "m.py")[0]
    assert parse_unit(unit).name == "m"


def test_file_without_functions():
    assert split_source("x = 1\n", "m.py") == []


# ---- corpus walking ----

def test_unparseable_and_bad_encoding_files_are_not_fatal(tmp_path):
    (tmp_path / "good.py").write_text("def ok():\n    return 1\n")
    (tmp_path / "bad_syntax.py").write_text("def (:\n")
    (tmp_path / "bad_bytes.py").write_bytes(b"def f():\n    return '\xff\xfe'\n")
    result = ingest_corpus(tmp_path)
    assert [u.unit_id for u in result.units] == [
        "bad_bytes.py::<module>",
        "bad_syntax.py::<module>",
        "good.py::ok",
    ]
    status = {u.unit_id: u.parse_status for u in result.units}
    assert status["good.py::ok"] == "ok"
    assert status["bad_bytes.py::<module>"] == "failed"
    assert status["bad_syntax.py::<module>"] == "failed"
    assert sorted(f.rel_path for f in result.failed_files) == ["bad_bytes.py", "bad_syntax.py"]
    assert result.files_scanned == 3
    only_good = ingest_corpus(tmp_path, include_failed=False)
    assert [u.unit_id for u in only_good.units] == ["good.py::ok"]


def test_encoding_cookie_is_respected(tmp_path):
    (tmp_path / "latin.py").write_bytes(
        b"# -*- coding: latin-1 -*-\ndef f():\n    return '\xe9'\n"
    )
    result = ingest_corpus(tmp_path)
    assert [u.unit_id for u in result.units] == ["latin.py::f"]
    assert result.failed_files == []


def test_hidden_and_vendor_dirs_skipped(tmp_path):
    for d in (".venv", ".git", "__pycache__", "node_modules"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x.py").write_text("def hidden():\n    pass\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "y.py").write_text("def shown():\n    pass\n")
    result = ingest_corpus(tmp_path)
    assert [u.unit_id for u in result.units] == ["pkg/y.py::shown"]


def test_single_file_input(tmp_path):
    path = tmp_path / "one.py"
    path.write_text("def f():\n    pass\n")
    assert [u.unit_id for u in ingest_corpus(path).units] == ["one.py::f"]


# ---- persistence and CLI ----

def test_save_load_roundtrip(tmp_path):
    units = ingest_corpus(CORPUS).units
    out = tmp_path / "idx" / "units.jsonl"
    save_units(units, out)
    assert load_units(out) == units


def test_cli_writes_units_and_reports(tmp_path, capsys):
    out = tmp_path / "units.jsonl"
    assert main([str(CORPUS), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert re.search(r"units\s+: 16", text)
    assert re.search(r"failed files\s+: 1", text)
    assert re.search(r"broken_syntax\.py \(line \d+\)", text)
    assert len(load_units(out)) == 16
    failed = load_failed(tmp_path / "failed_files.json")
    assert [f.rel_path for f in failed] == ["broken_syntax.py"]


def test_cli_skip_failed(tmp_path):
    out = tmp_path / "units.jsonl"
    assert main([str(CORPUS), "--out", str(out), "--skip-failed"]) == 0
    assert len(load_units(out)) == 15


def test_failed_files_roundtrip(tmp_path):
    failed = ingest_corpus(CORPUS).failed_files
    save_failed(failed, tmp_path / "f.json")
    assert load_failed(tmp_path / "f.json") == failed
    assert load_failed(tmp_path / "missing.json") == []


def test_fingerprint_changes_with_source_and_ignores_order():
    units = ingest_corpus(CORPUS).units
    same = fingerprint_units(reversed(units))
    assert same == fingerprint_units(units)
    units[0].source_text += "\n# edit"
    assert fingerprint_units(units) != same
