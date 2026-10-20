import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from structsearch.indexing import build_all, ensure_index
from structsearch.ingestion import corpus_signature
from structsearch.interface.cli import main
from structsearch.interface.format import excerpt_lines, format_results
from structsearch.ingestion import ingest_corpus
from structsearch.retrieval import bm25_search

ROOT = Path(__file__).parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "sample_corpus"


@pytest.fixture()
def corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


def _run(capsys, tmp_path, corpus, *extra):
    code = main(["search", *extra, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---- retrieval layer ----

def test_bm25_search_returns_ranked_results_with_evidence(tmp_path):
    result, index = build_all(CORPUS, tmp_path)
    units_by_id = {u.unit_id: u for u in result.units}
    failed = {f.rel_path: f for f in result.failed_files}
    results = bm25_search(index, units_by_id, "read file", k=3, query_id="q7", failed_by_path=failed)
    assert len(results) == 3
    top = results[0]
    assert top.query_id == "q7" and top.unit_id in {"files.py::read_config_safe", "files.py::read_lines"}
    assert top.structural_score == 0.0 and top.graph_score is None
    assert top.final_score == top.text_score > 0
    assert any(e.startswith("term match in name: read") for e in top.evidence)
    scores = [r.final_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_failed_unit_evidence_mentions_parse_failure(tmp_path):
    result, index = build_all(CORPUS, tmp_path)
    units_by_id = {u.unit_id: u for u in result.units}
    failed = {f.rel_path: f for f in result.failed_files}
    top = bm25_search(index, units_by_id, "broken syntax", 1, failed_by_path=failed)[0]
    assert top.unit_id == "broken_syntax.py::<module>"
    assert any("did not parse" in e and "SyntaxError" in e for e in top.evidence)


# ---- formatting ----

def test_excerpt_uses_real_file_line_numbers():
    unit = {u.unit_id: u for u in ingest_corpus(CORPUS).units}["trees.py::factorial"]
    lines, hidden = excerpt_lines(unit, 2)
    assert lines[0] == (17, "def factorial(n):") and len(lines) == 2 and hidden == 3
    assert excerpt_lines(unit, 99)[1] == 0


def test_format_no_results():
    text = format_results("zzz", [], {}, 16)
    assert "No results." in text


# ---- CLI: search ----

def test_search_text_output(capsys, tmp_path, corpus):
    code, out, err = _run(capsys, tmp_path, corpus, "read file", "-k", "2", "--lines", "3")
    assert code == 0
    assert "files.py::read_lines" in out and "files.py:21-24" in out
    assert "term match in name: read" in out
    assert "21 | def read_lines(path):" in out
    assert "(+1 more lines)" in out
    assert "index built (no index yet)" in err
    assert (tmp_path / "idx" / "bm25_index.json").exists()


def test_k_is_respected_and_second_run_reuses_index(capsys, tmp_path, corpus):
    _run(capsys, tmp_path, corpus, "file", "-k", "1")
    code, out, err = _run(capsys, tmp_path, corpus, "file", "-k", "1")
    assert code == 0 and err == ""
    assert out.count("score ") == 1


def test_json_output_is_clean_and_complete(capsys, tmp_path, corpus):
    code, out, err = _run(capsys, tmp_path, corpus, "recursive tree traversal", "-k", "2", "--json", "--query-id", "q1")
    payload = json.loads(out)  # stdout contains only JSON
    assert payload["query"] == "recursive tree traversal" and payload["mode"] == "bm25"
    first = payload["results"][0]
    assert first["unit_id"] == "trees.py::inorder_traverse"
    assert first["query_id"] == "q1" and first["graph_score"] is None
    for key in ("text_score", "structural_score", "final_score", "evidence", "file_path",
                "start_line", "end_line", "name", "parse_status", "excerpt"):
        assert key in first
    assert "index built" in err


def test_failed_file_result_is_flagged(capsys, tmp_path, corpus):
    _, out, _ = _run(capsys, tmp_path, corpus, "broken syntax", "-k", "1")
    assert "[parse failed]" in out and "text match only" in out


def test_skip_failed_removes_broken_file(capsys, tmp_path, corpus):
    _, out, _ = _run(capsys, tmp_path, corpus, "broken syntax", "--skip-failed")
    assert "broken_syntax.py::<module>" not in out


def test_no_results_and_stopword_only_query(capsys, tmp_path, corpus):
    _, out, _ = _run(capsys, tmp_path, corpus, "zzzzqqqq")
    assert "No results." in out
    _, out, err = _run(capsys, tmp_path, corpus, "find all the functions")
    assert "No results." in out and "no searchable terms" in err


def test_errors_return_exit_code_2(capsys, tmp_path):
    code = main(["search", "x", "--corpus", str(tmp_path / "missing"), "--index-dir", str(tmp_path / "i")])
    assert code == 2 and "corpus path not found" in capsys.readouterr().err
    code = main(["search", "x", "-k", "0", "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "i")])
    assert code == 2 and "-k must be at least 1" in capsys.readouterr().err


# ---- index freshness ----

def test_changed_corpus_triggers_rebuild(capsys, tmp_path, corpus):
    _run(capsys, tmp_path, corpus, "file")
    (corpus / "extra.py").write_text('def send_email(address):\n    """Send an email message."""\n    return address\n')
    code, out, err = _run(capsys, tmp_path, corpus, "send email", "-k", "1")
    assert "corpus files changed" in err
    assert "extra.py::send_email" in out


def test_rebuild_flag_and_changed_corpus_path(capsys, tmp_path, corpus):
    _run(capsys, tmp_path, corpus, "file")
    _, _, err = _run(capsys, tmp_path, corpus, "file", "--rebuild")
    assert "rebuild requested" in err
    other = tmp_path / "other"
    shutil.copytree(CORPUS, other)
    _, _, err = _run(capsys, tmp_path, other, "file")
    assert "corpus path changed" in err


def test_ensure_index_reports_reason(tmp_path, corpus):
    idx = tmp_path / "idx"
    _, _, reason = ensure_index(corpus, idx)
    assert reason == "no index yet"
    _, _, reason = ensure_index(corpus, idx)
    assert reason is None
    _, _, reason = ensure_index(corpus, idx, include_failed=False)
    assert reason == "failed-file setting changed"


def test_corpus_signature_tracks_files(tmp_path, corpus):
    first = corpus_signature(corpus)
    assert corpus_signature(corpus) == first
    (corpus / "new.py").write_text("x = 1\n")
    changed = corpus_signature(corpus)
    assert changed != first
    (corpus / "new.py").write_text("x = 12345\n")
    assert corpus_signature(corpus) != changed


# ---- CLI: index and entry point ----

def test_index_subcommand(capsys, tmp_path, corpus):
    code = main(["index", str(corpus), "--index-dir", str(tmp_path / "idx")])
    out = capsys.readouterr().out
    assert code == 0
    assert "units indexed : 16" in out and "failed files  : 1" in out and "broken_syntax.py" in out


def test_python_dash_m_entry_point(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, "-m", "structsearch", "search", "factorial", "-k", "1",
         "--corpus", str(CORPUS), "--index-dir", str(tmp_path / "idx")],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "trees.py::factorial" in proc.stdout
