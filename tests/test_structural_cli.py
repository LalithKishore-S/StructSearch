import json
import shutil
from pathlib import Path

import pytest

import structsearch.interface.cli as cli
from structsearch.interface.cli import main
from structsearch.llm import LLMSettings

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture()
def corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


def run(capsys, tmp_path, corpus, *args):
    code = main(["search", *args, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_structural_search_text_output(capsys, tmp_path, corpus):
    code, out, err = run(capsys, tmp_path, corpus, "recursive traversal", "--mode", "structural")
    assert code == 0 and "mode: structural" in out
    assert "trees.py::inorder_traverse" in out and "structural match: recursion" in out
    assert "structural profile (rules): recursion" in err
    assert "count_nodes" not in out


def test_structural_search_json_includes_profile(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "recursive", "--mode", "structural", "--json", "-k", "1")
    payload = json.loads(out)
    assert code == 0 and payload["mode"] == "structural" and len(payload["results"]) == 1
    assert payload["profile"]["source"] == "rules"
    assert payload["profile"]["constraints"][0]["features"] == ["self_call"]
    assert payload["results"][0]["structural_score"] == 1.0


def test_structural_search_without_structural_wording(capsys, tmp_path, corpus):
    code, out, err = run(capsys, tmp_path, corpus, "parse a csv", "--mode", "structural")
    assert code == 0 and "No results" in out and "no structural requirements" in err


def test_use_llm_falls_back_when_ollama_is_down(capsys, tmp_path, corpus, monkeypatch):
    dead = LLMSettings(enabled=True, host="http://127.0.0.1:9", timeout_seconds=2)
    monkeypatch.setattr(cli, "_llm_settings", lambda args, cfg: dead)
    code, out, err = run(capsys, tmp_path, corpus, "recursive", "--mode", "structural", "--use-llm")
    assert code == 0 and "inorder_traverse" in out and "Cannot reach Ollama" in err


def test_use_llm_flag_enables_llm_settings():
    ns = type("A", (), {"use_llm": True, "llm_model": "tiny"})()
    s = cli._llm_settings(ns, {"llm": {"enabled": False, "model": "big"}})
    assert s.enabled and s.model == "tiny"
    ns = type("A", (), {"use_llm": False, "llm_model": None})()
    assert not cli._llm_settings(ns, {"llm": {"enabled": False}}).enabled
    assert cli._llm_settings(ns, {"llm": {"enabled": True}}).enabled  # config can switch it on too


def test_profile_command(capsys):
    assert main(["profile", "read a file without error handling"]) == 0
    out = capsys.readouterr().out
    assert "mapper: rules" in out and "absent" in out and "try_count" in out
    assert main(["profile", "parse a csv"]) == 0
    assert "no structural requirements" in capsys.readouterr().out
    assert main(["profile", "nested loops", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "nested loops" and payload["constraints"][0]["op"] == "at_least"


def test_other_modes_still_work(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "factorial", "--mode", "bm25")
    assert code == 0 and "trees.py::factorial" in out
