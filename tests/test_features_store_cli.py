import json
import shutil
from pathlib import Path

import pytest

from structsearch.ingestion import ingest_corpus
from structsearch.interface.cli import main
from structsearch.parsing import (
    AST_FILE,
    ensure_ast_records,
    extract_all,
    load_ast_records,
    save_ast_records,
)

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture()
def corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


# ---- store ----

def test_save_load_roundtrip(tmp_path):
    units = ingest_corpus(CORPUS).units
    records = extract_all(units)
    save_ast_records(records, tmp_path / AST_FILE, "fp")
    fingerprint, loaded = load_ast_records(tmp_path / AST_FILE)
    assert fingerprint == "fp" and loaded == records


def test_load_returns_none_for_missing_corrupt_or_old_version(tmp_path):
    assert load_ast_records(tmp_path / "missing.jsonl") is None
    (tmp_path / "bad.jsonl").write_text("not json\n")
    assert load_ast_records(tmp_path / "bad.jsonl") is None
    (tmp_path / "old.jsonl").write_text('{"_meta": {"extraction_version": "0", "fingerprint": "x"}}\n')
    assert load_ast_records(tmp_path / "old.jsonl") is None


def test_ensure_ast_records_lifecycle(tmp_path):
    units = ingest_corpus(CORPUS).units
    records, reason = ensure_ast_records(units, tmp_path)
    assert reason == "no AST features yet" and [r.unit_id for r in records] == [u.unit_id for u in units]
    again, reason = ensure_ast_records(units, tmp_path)
    assert reason is None and again == records
    units[2].source_text += "\n# edited"
    _, reason = ensure_ast_records(units, tmp_path)
    assert reason == "units changed"
    _, reason = ensure_ast_records(units[:5], tmp_path)
    assert reason == "units changed"


# ---- CLI ----

def _features(capsys, tmp_path, corpus, *extra):
    code = main(["features", *extra, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_features_table(capsys, tmp_path, corpus):
    code, out, err = _features(capsys, tmp_path, corpus)
    assert code == 0 and "AST features extracted" in err
    header = out.splitlines()[0]
    assert header.split()[:2] == ["unit", "if"] and "self" in header
    row = next(l for l in out.splitlines() if l.startswith("trees.py::factorial"))
    assert row.split()[-1] == "1"  # self_call column
    assert "broken_syntax.py::<module>" in out and "did not parse" in out
    _, _, err = _features(capsys, tmp_path, corpus)
    assert err == ""  # cached


def test_features_for_one_unit_exact_and_partial(capsys, tmp_path, corpus):
    code, out, _ = _features(capsys, tmp_path, corpus, "trees.py::inorder_traverse")
    assert code == 0 and "self_call_count" in out and "node types:" in out
    assert out.count("trees.py::") == 1
    code, out, _ = _features(capsys, tmp_path, corpus, "factorial")
    assert code == 0 and "trees.py::factorial" in out


def test_features_json_and_errors(capsys, tmp_path, corpus):
    code, out, _ = _features(capsys, tmp_path, corpus, "utils.py::add", "--json")
    payload = json.loads(out)
    assert payload[0]["unit_id"] == "utils.py::add" and payload[0]["features"]["return_count"] == 1.0
    code, _, err = _features(capsys, tmp_path, corpus, "no_such_unit")
    assert code == 2 and "no unit matches" in err
    code = main(["features", "--corpus", str(tmp_path / "missing"), "--index-dir", str(tmp_path / "i")])
    assert code == 2 and "corpus path not found" in capsys.readouterr().err


def test_features_refresh_when_corpus_changes(capsys, tmp_path, corpus):
    _features(capsys, tmp_path, corpus)
    (corpus / "extra.py").write_text("def new_fn(x):\n    if x:\n        return x\n")
    code, out, err = _features(capsys, tmp_path, corpus, "extra.py::new_fn")
    assert code == 0 and "if_count" in out and "units changed" in err
