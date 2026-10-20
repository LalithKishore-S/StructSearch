from pathlib import Path

from structsearch.config import load_config
from structsearch.indexing import BM25Index, build_all, load_all
from structsearch.indexing.cli import main
from structsearch.ingestion import load_failed, load_units, save_units

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def test_build_all_writes_three_files(tmp_path):
    result, index = build_all(CORPUS, tmp_path / "idx")
    for name in ("units.jsonl", "failed_files.json", "bm25_index.json"):
        assert (tmp_path / "idx" / name).exists()
    assert len(result.units) == 16 and len(index.unit_ids) == 16
    assert [f.rel_path for f in load_failed(tmp_path / "idx" / "failed_files.json")] == [
        "broken_syntax.py"
    ]


def test_build_all_skip_failed(tmp_path):
    result, index = build_all(CORPUS, tmp_path, include_failed=False)
    assert len(index.unit_ids) == 15
    assert "broken_syntax.py::<module>" not in index.unit_ids


def test_load_all_reuses_fresh_index(tmp_path):
    _, built = build_all(CORPUS, tmp_path)
    units, loaded = load_all(tmp_path)
    assert len(units) == 16
    assert loaded.fingerprint == built.fingerprint != ""
    assert loaded.search("read file", 3) == built.search("read file", 3)


def test_load_all_rebuilds_stale_index(tmp_path):
    build_all(CORPUS, tmp_path)
    units = load_units(tmp_path / "units.jsonl")
    units = [u for u in units if u.unit_id != "utils.py::add"]
    save_units(units, tmp_path / "units.jsonl")  # units changed after indexing
    units, index = load_all(tmp_path)
    assert "utils.py::add" not in index.unit_ids
    assert BM25Index.load(tmp_path / "bm25_index.json").unit_ids == index.unit_ids


def test_config_bm25_section_loaded():
    weights = load_config()["bm25"]["field_weights"]
    assert weights["name"] > weights["code"]


def test_cli_build_and_query(tmp_path, capsys):
    assert main([str(CORPUS), "--index-dir", str(tmp_path), "--query", "read file", "-k", "2"]) == 0
    out = capsys.readouterr().out
    assert "units indexed : 16" in out
    assert "files.py::read_lines" in out and "matched ->" in out


def test_cli_load_flags_failed_units(tmp_path, capsys):
    main([str(CORPUS), "--index-dir", str(tmp_path)])
    capsys.readouterr()
    assert main(["--load", "--index-dir", str(tmp_path), "--query", "broken syntax"]) == 0
    out = capsys.readouterr().out
    assert "broken_syntax.py::<module>" in out and "[parse failed]" in out
