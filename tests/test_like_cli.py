import json
import shutil
from pathlib import Path

import pytest

from structsearch.ingestion import ingest_corpus
from structsearch.interface.cli import main
from structsearch.parsing import extract_all_fragments, snippet_terms
from structsearch.retrieval.like import FragmentIndex, like_search

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"

EXTRA = '''def retry_all(jobs):
    """Run every job, logging failures."""
    for job in jobs:
        try:
            job.run()
        except Exception:
            print("failed")


def run_then_guard(jobs):
    """Loop first, handle errors afterwards."""
    for job in jobs:
        job.run()
    try:
        jobs.close()
    except Exception:
        pass


def leaky_read(path):
    handle = open(path)
    return handle.read()
'''


@pytest.fixture()
def corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    (dest / "extra.py").write_text(EXTRA)
    return dest


def run(capsys, tmp_path, corpus, *args, command="search"):
    code = main([command, *args, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx")])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---- FragmentIndex / like_search ----

@pytest.fixture(scope="module")
def indexed():
    result = ingest_corpus(CORPUS)
    return {u.unit_id: u for u in result.units}, extract_all_fragments(result.units)


def test_like_ranks_structurally_similar_function_first(indexed):
    units, fragments = indexed
    wanted = snippet_terms("q = 'select ' + name\nreturn db.execute(q)\n")
    results = like_search(FragmentIndex(fragments), units, wanted, k=3)
    assert results[0].unit_id == "db.py::find_user_unsafe"
    assert results[0].final_score == results[0].structural_score > results[1].final_score
    assert any("BinOp:Add before Call:execute" in line for line in results[0].evidence)
    assert all(r.text_score == 0.0 and r.graph_score is None for r in results)


def test_like_excludes_failed_units_and_respects_k(indexed):
    units, fragments = indexed
    wanted = snippet_terms("def f(x):\n    return x\n")
    results = like_search(FragmentIndex(fragments), units, wanted, k=50)
    assert "broken_syntax.py::<module>" not in {r.unit_id for r in results}
    assert len(like_search(FragmentIndex(fragments), units, wanted, k=2)) == 2
    assert like_search(FragmentIndex(fragments), units, wanted, k=0) == []


def test_like_is_deterministic_and_handles_empty_index(indexed):
    units, fragments = indexed
    wanted = snippet_terms("for x in xs:\n    go(x)\n")
    index = FragmentIndex(fragments)
    assert [r.unit_id for r in like_search(index, units, wanted, k=20)] == [r.unit_id for r in like_search(index, units, wanted, k=20)]
    assert like_search(FragmentIndex([]), units, wanted, k=5) == [] and len(FragmentIndex([])) == 0
    assert like_search(index, units, {"u:NeverSeen": 1}, k=5) == []


def test_like_evidence_prefers_relations_over_bare_node_kinds(indexed):
    units, fragments = indexed
    index = FragmentIndex(fragments)
    wanted = snippet_terms("try:\n    with open(p) as h:\n        data = load(h)\nexcept OSError:\n    data = None\n")
    top = like_search(index, units, wanted, k=1)[0]
    assert top.unit_id == "files.py::read_config_safe"
    assert top.evidence and all(line.startswith("shared structure:") for line in top.evidence)
    assert not any(line.startswith("shared structure: has ") for line in top.evidence)


# ---- CLI: structural + patterns ----

def test_structural_pattern_flag_finds_try_inside_loop(capsys, tmp_path, corpus):
    code, out, err = run(capsys, tmp_path, corpus, "x", "--mode", "structural", "--pattern", "For|While//Try", "--lines", "0")
    assert code == 0 and "extra.py::retry_all" in out and "extra.py::run_then_guard" not in out
    assert "[pattern: For|While//Try]" in out and "structure found: For contains Try" in out
    assert "structural profile" in err


def test_natural_language_query_maps_to_the_same_pattern(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "try except inside a loop", "--mode", "structural", "--lines", "0")
    assert code == 0 and "extra.py::retry_all" in out and "run_then_guard" not in out


def test_open_without_with_query(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "read a file without a context manager", "--mode", "structural", "--lines", "0", "--json")
    payload = json.loads(out)
    assert code == 0 and [r["unit_id"] for r in payload["results"]] == ["extra.py::leaky_read"]
    assert payload["results"][0]["final_score"] == 1.0
    assert [p["pattern"] for p in payload["profile"]["patterns"]] == ["Call:open and !With//Call:open"]


def test_sql_query_separates_unsafe_from_parameterized(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "sql injection", "--mode", "structural", "--lines", "0", "--json")
    ids = {r["unit_id"] for r in json.loads(out)["results"]}
    assert ids == {"db.py::find_user_unsafe", "db.py::count_rows"}


def test_bad_pattern_flag_is_a_clean_error(capsys, tmp_path, corpus):
    code, out, err = run(capsys, tmp_path, corpus, "x", "--mode", "structural", "--pattern", "Foo//Try")
    assert code == 2 and "bad --pattern" in err and "unknown label 'Foo'" in err and out == ""
    assert main(["profile", "x", "--pattern", "For//"]) == 2
    assert "bad --pattern" in capsys.readouterr().err


def test_profile_shows_patterns(capsys):
    assert main(["profile", "sql injection in a loop", "--pattern", "!With//Call:open"]) == 0
    out = capsys.readouterr().out
    assert out.count("pattern") == 2 and "SQL built by string concatenation/formatting" in out
    assert main(["profile", "try except inside a loop", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["patterns"][0]["pattern"] == "For|While//Try" and payload["constraints"] == []


# ---- CLI: like ----

def test_like_with_inline_snippet(capsys, tmp_path, corpus):
    snippet = "for item in items:\n    try:\n        item.run()\n    except Exception:\n        pass\n"
    code, out, _ = run(capsys, tmp_path, corpus, snippet, "--mode", "like", "-k", "2", "--lines", "0")
    assert code == 0 and "mode: like" in out
    assert out.index("extra.py::retry_all") < out.index("extra.py::run_then_guard") if "run_then_guard" in out else True
    first = out.split(" 1. ", 1)[1].split("\n", 1)[0]
    assert "extra.py::retry_all" in first and "shared structure:" in out


def test_like_with_snippet_file(capsys, tmp_path, corpus):
    path = tmp_path / "snippet.py"
    path.write_text("handle = open(path)\nreturn handle.read()\n")
    code, out, _ = run(capsys, tmp_path, corpus, "@" + str(path), "--mode", "like", "-k", "1", "--lines", "0")
    assert code == 0 and "extra.py::leaky_read" in out


def test_like_errors(capsys, tmp_path, corpus):
    code, _, err = run(capsys, tmp_path, corpus, "def (:", "--mode", "like")
    assert code == 2 and "not valid Python" in err
    code, _, err = run(capsys, tmp_path, corpus, "@" + str(tmp_path / "nope.py"), "--mode", "like")
    assert code == 2 and "cannot read snippet file" in err


def test_like_json_has_scores_and_evidence(capsys, tmp_path, corpus):
    code, out, _ = run(capsys, tmp_path, corpus, "return a + b\n", "--mode", "like", "--json", "-k", "2", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and payload["mode"] == "like" and payload["results"][0]["structural_score"] > 0


# ---- CLI: fragments ----

def test_fragments_command(capsys, tmp_path, corpus):
    code, out, err = run(capsys, tmp_path, corpus, "db.py::find_user_unsafe", command="fragments")
    assert code == 0 and "fragments extracted" in err
    assert "ord (" in out and "BinOp:Add before Call:execute" in out and "ad (" in out
    code, out, _ = run(capsys, tmp_path, corpus, "find_user_unsafe", "--kind", "ord", command="fragments")
    assert "ord (" in out and "ad (" not in out
    code, out, _ = run(capsys, tmp_path, corpus, "retry_all", "--json", "--kind", "ad", command="fragments")
    data = json.loads(out)
    assert "ad:For//Try" in data[0]["terms"] and all(t.startswith("ad:") for t in data[0]["terms"])


def test_fragments_errors_and_failed_files(capsys, tmp_path, corpus):
    code, _, err = run(capsys, tmp_path, corpus, "no_such_unit", command="fragments")
    assert code == 2 and "no unit matches" in err
    code, out, _ = run(capsys, tmp_path, corpus, "broken_syntax", command="fragments")
    assert code == 0 and "did not parse" in out


def test_fragments_refresh_when_corpus_changes(capsys, tmp_path, corpus):
    run(capsys, tmp_path, corpus, "retry_all", command="fragments")
    (corpus / "extra.py").write_text(EXTRA + "\n\ndef added():\n    return 1\n")
    code, out, err = run(capsys, tmp_path, corpus, "added", command="fragments")
    assert code == 0 and "units changed" in err and "added" in out
