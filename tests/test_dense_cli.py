import json
import shutil
from pathlib import Path

import pytest

import structsearch.interface.cli as cli
import structsearch.interface.service as service
from structsearch.config import load_config, validate_config
from structsearch.indexing import EmbeddingError
from structsearch.interface.cli import main

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture()
def corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


def _search(capsys, tmp_path, corpus, *extra):
    code = main(["search", *extra, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx"),
                 "--embedder", "hashing"])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_dense_mode_end_to_end_and_cache(capsys, tmp_path, corpus):
    code, out, err = _search(capsys, tmp_path, corpus, "validate input", "--mode", "dense", "-k", "2", "--lines", "1")
    assert code == 0
    assert "mode: dense" in out and "db.py::validate_user_input" in out
    assert "semantic similarity" in out
    assert "dense index built (no dense index yet)" in err and "lexical, not semantic" in err
    assert (tmp_path / "idx" / "dense_vectors.npy").exists()
    code, out, err = _search(capsys, tmp_path, corpus, "read file", "--mode", "dense", "-k", "1")
    assert code == 0 and "dense index built" not in err  # reused


def test_dense_json_output(capsys, tmp_path, corpus):
    code, out, _ = _search(capsys, tmp_path, corpus, "recursive tree traversal", "--mode", "dense", "-k", "3", "--json")
    payload = json.loads(out)
    assert payload["mode"] == "dense" and payload["embedding_model"] == "hashing-256"
    first = payload["results"][0]
    assert first["dense_score"] == first["final_score"] and first["text_score"] == 0.0
    assert len(payload["results"]) == 3


def test_changed_corpus_refreshes_dense_index(capsys, tmp_path, corpus):
    _search(capsys, tmp_path, corpus, "file", "--mode", "dense")
    (corpus / "extra.py").write_text('def send_email(address):\n    """Send an email message."""\n    return address\n')
    code, out, err = _search(capsys, tmp_path, corpus, "send email", "--mode", "dense", "-k", "1")
    assert "units changed (1 to embed)" in err
    assert "extra.py::send_email" in out


def test_rebuild_flag_rebuilds_dense(capsys, tmp_path, corpus):
    _search(capsys, tmp_path, corpus, "file", "--mode", "dense")
    _, _, err = _search(capsys, tmp_path, corpus, "file", "--mode", "dense", "--rebuild")
    assert "dense index built (rebuild requested)" in err


def test_index_dense_flag(capsys, tmp_path, corpus):
    code = main(["index", str(corpus), "--index-dir", str(tmp_path / "idx"), "--dense", "--embedder", "hashing"])
    out = capsys.readouterr().out
    assert code == 0 and "dense vectors : 16 x 256 (model hashing-256)" in out


def test_bm25_mode_does_not_touch_embedder(capsys, tmp_path, corpus, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("embedder must not be created in bm25 mode")

    monkeypatch.setattr(service, "make_embedder", boom)
    code = main(["search", "read file", "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    assert code == 0 and "files.py::read_lines" in capsys.readouterr().out


def test_embedding_error_gives_exit_code_3(capsys, tmp_path, corpus, monkeypatch):
    def unavailable(settings):
        raise EmbeddingError("Cannot reach Ollama at http://localhost:11434. Start it (ollama serve)")

    monkeypatch.setattr(service, "make_embedder", unavailable)
    code = main(["search", "x", "--mode", "dense", "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    assert code == 3
    assert "ollama serve" in capsys.readouterr().err


def test_config_dense_section():
    cfg = load_config()
    assert cfg["dense"]["model"] == "nomic-embed-text"
    assert cfg["dense"]["doc_prefix"] == "search_document: " and cfg["dense"]["query_prefix"] == "search_query: "
    good = {"top_k": 5, "weights": {"text": 1, "structural": 1, "graph": 1}}
    validate_config({**good, "dense": {"backend": "hashing", "batch_size": 2}})
    for bad in ({"backend": "x"}, {"batch_size": 0}, {"max_chars": 10}, {"timeout_seconds": 0}, {"model": " "}):
        with pytest.raises(ValueError):
            validate_config({**good, "dense": bad})
