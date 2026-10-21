import json

import pytest

from structsearch.evaluation import (
    BenchmarkReport,
    check_benchmark,
    freeze_benchmark,
    read_records,
)
from structsearch.interface.cli import main

UNITS = ["a.py::f", "a.py::g", "b.py::h"]


def write(tmp_path, queries, labels):
    qp, lp = tmp_path / "queries.json", tmp_path / "labels.jsonl"
    qp.write_text(json.dumps(queries))
    lp.write_text("\n".join(json.dumps(r) for r in labels))
    return qp, lp


def q(qid, text="find something", category="lexical", split="dev", **extra):
    return {"query_id": qid, "query": text, "category": category, "split": split, **extra}


def lab(qid, unit, rel, category="lexical", split="dev"):
    return {"query_id": qid, "unit_id": unit, "relevance": rel, "query_category": category, "split": split}


def pool(qid, relevant, category="lexical", split="dev", units=UNITS):
    return [lab(qid, u, 1 if u in relevant else 0, category, split) for u in units]


def good(tmp_path):
    queries = [q("a", "alpha"), q("b", "beta", "relationship", "test")]
    labels = pool("a", {"a.py::f"}) + pool("b", {"b.py::h"}, "relationship", "test")
    return write(tmp_path, queries, labels)


def problems(tmp_path, queries, labels, units=UNITS, **kw):
    qp, lp = write(tmp_path, queries, labels)
    return check_benchmark(qp, lp, units, **kw).problems


# ------------------------------------------------------------------ reading


def test_read_records_formats(tmp_path):
    (tmp_path / "a.json").write_text('[{"x": 1}]')
    (tmp_path / "b.jsonl").write_text('{"x": 1}\n\n{"x": 2}\n')
    (tmp_path / "c.csv").write_text("x,y\n1,2\n")
    assert read_records(tmp_path / "a.json") == [{"x": 1}]
    assert read_records(tmp_path / "b.jsonl") == [{"x": 1}, {"x": 2}]
    assert read_records(tmp_path / "c.csv") == [{"x": "1", "y": "2"}]


# ------------------------------------------------------------------ a valid benchmark


def test_valid_benchmark_has_no_problems_and_reports_stats(tmp_path):
    qp, lp = good(tmp_path)
    report = check_benchmark(qp, lp, UNITS)
    assert isinstance(report, BenchmarkReport) and report.problems == []
    assert report.stats["queries"] == 2
    assert report.stats["by_split_category"] == {"dev/lexical": 1, "test/relationship": 1}
    assert report.stats["labels"] == 6 and report.stats["relevant_per_query"] == {"a": 1, "b": 1}


def test_size_outside_20_to_40_is_a_warning_not_a_problem(tmp_path):
    qp, lp = good(tmp_path)
    report = check_benchmark(qp, lp, UNITS)
    assert any("20-40" in w for w in report.warnings)


# ------------------------------------------------------------------ query problems


def test_query_fields_ids_and_values(tmp_path):
    cases = [
        ([q("a"), q("a", "other")], "duplicate query_id"),
        ([q("a", category="semantic")], "category"),
        ([q("a", split="train")], "split"),
        ([q("a", text="  ")], "empty"),
        ([q("a", "same words"), q("b", "Same  Words")], "same text"),
        ([{"query_id": "a", "category": "lexical", "split": "dev"}], "missing"),
    ]
    for queries, needle in cases:
        labels = [r for query in queries if "query" in query for r in pool(query["query_id"], {"a.py::f"})]
        found = problems(tmp_path, queries, labels)
        assert any(needle in p for p in found), (needle, found)


def test_paraphrase_group_must_share_split_category_and_relevant_units(tmp_path):
    queries = [q("a", "one", group="g"), q("b", "two", split="test", group="g")]
    labels = pool("a", {"a.py::f"}) + pool("b", {"a.py::f"}, split="test")
    assert any("group g" in p and "split" in p for p in problems(tmp_path, queries, labels))
    queries = [q("a", "one", group="g"), q("b", "two", group="g")]
    labels = pool("a", {"a.py::f"}) + pool("b", {"a.py::g"})
    assert any("group g" in p and "relevant" in p for p in problems(tmp_path, queries, labels))
    queries = [q("a", "one", group="g"), q("b", "two", "relationship", group="g")]
    labels = pool("a", {"a.py::f"}) + pool("b", {"a.py::f"}, "relationship")
    assert any("group g" in p and "category" in p for p in problems(tmp_path, queries, labels))


# ------------------------------------------------------------------ label problems


def test_label_problems(tmp_path):
    base = [q("a")]
    full = pool("a", {"a.py::f"})
    cases = [
        (full + [lab("zzz", "a.py::f", 1)], "unknown query"),
        (full[:-1] + [lab("a", "nope.py::x", 0)], "unknown unit"),
        (full + [lab("a", "a.py::f", 1)], "duplicate label"),
        (pool("a", set()), "no relevant"),
        ([lab("a", u, 1, split="test") for u in UNITS[:1]] + full[1:], "split"),
        ([lab("a", u, 1, category="relationship") for u in UNITS[:1]] + full[1:], "category"),
        ([lab("a", "a.py::f", -1)] + full[1:], "relevance"),
        ([lab("a", "a.py::f", "x")] + full[1:], "relevance"),
        (full[:2], "not judged"),
        ([], "no labels"),
    ]
    for labels, needle in cases:
        found = problems(tmp_path, base, labels)
        assert any(needle in p for p in found), (needle, found)


def test_pool_completeness_is_only_checked_when_units_are_given(tmp_path):
    qp, lp = write(tmp_path, [q("a")], pool("a", {"a.py::f"})[:2])
    assert check_benchmark(qp, lp, None).problems == []
    assert any("not judged" in p for p in check_benchmark(qp, lp, UNITS).problems)


def test_graded_relevance_is_accepted(tmp_path):
    labels = [lab("a", "a.py::f", 2), lab("a", "a.py::g", 1), lab("a", "b.py::h", 0)]
    assert problems(tmp_path, [q("a")], labels) == []


# ------------------------------------------------------------------ freezing the split


def test_freeze_then_check_detects_changes(tmp_path):
    qp, lp = good(tmp_path)
    lock = freeze_benchmark(qp, lp, UNITS)
    assert lock.exists() and check_benchmark(qp, lp, UNITS).problems == []
    # moving a query between splits after the freeze is reported
    queries = json.loads(qp.read_text())
    queries[0]["split"] = "test"
    qp.write_text(json.dumps(queries))
    labels = [dict(json.loads(l), split="test") if json.loads(l)["query_id"] == "a" else json.loads(l)
              for l in lp.read_text().splitlines()]
    lp.write_text("\n".join(json.dumps(r) for r in labels))
    assert any("changed since it was frozen" in p for p in check_benchmark(qp, lp, UNITS).problems)


def test_changed_label_after_freeze_is_reported(tmp_path):
    qp, lp = good(tmp_path)
    freeze_benchmark(qp, lp, UNITS)
    rows = [json.loads(l) for l in lp.read_text().splitlines()]
    rows[1]["relevance"] = 1
    lp.write_text("\n".join(json.dumps(r) for r in rows))
    assert any("labels" in p and "frozen" in p for p in check_benchmark(qp, lp, UNITS).problems)


def test_freeze_refuses_an_invalid_benchmark(tmp_path):
    qp, lp = write(tmp_path, [q("a")], pool("a", set()))
    with pytest.raises(ValueError):
        freeze_benchmark(qp, lp, UNITS)
    assert not (tmp_path / "split.lock").exists()


def test_check_without_lock_notes_it(tmp_path):
    qp, lp = good(tmp_path)
    assert any("not frozen" in w for w in check_benchmark(qp, lp, UNITS).warnings)


# ------------------------------------------------------------------ command line


def run_cli(capsys, *args):
    code = main(["benchmark", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def make_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.py").write_text("def f():\n    return 1\n\ndef g():\n    return 2\n")
    (corpus / "b.py").write_text("def h():\n    return 3\n")
    return corpus


def test_cli_check_and_freeze(capsys, tmp_path):
    qp, lp = good(tmp_path)
    corpus = make_corpus(tmp_path)
    code, out, _ = run_cli(capsys, "check", "--queries", str(qp), "--labels", str(lp), "--corpus", str(corpus))
    assert code == 0 and "problems: 0" in out and "dev/lexical" in out
    code, out, _ = run_cli(capsys, "freeze", "--queries", str(qp), "--labels", str(lp), "--corpus", str(corpus))
    assert code == 0 and (tmp_path / "split.lock").exists()
    code, out, _ = run_cli(capsys, "check", "--queries", str(qp), "--labels", str(lp), "--corpus", str(corpus))
    assert code == 0 and "frozen" in out


def test_cli_check_fails_with_problems(capsys, tmp_path):
    qp, lp = write(tmp_path, [q("a")], pool("a", set()))
    code, out, _ = run_cli(capsys, "check", "--queries", str(qp), "--labels", str(lp), "--corpus", str(make_corpus(tmp_path)))
    assert code == 2 and "no relevant" in out


def test_cli_json_and_missing_files(capsys, tmp_path):
    qp, lp = good(tmp_path)
    code, out, _ = run_cli(capsys, "check", "--queries", str(qp), "--labels", str(lp), "--corpus", str(make_corpus(tmp_path)), "--json")
    assert code == 0 and json.loads(out)["problems"] == []
    code, _, err = run_cli(capsys, "check", "--queries", str(tmp_path / "nope.json"), "--labels", str(lp))
    assert code == 2 and "error" in err
