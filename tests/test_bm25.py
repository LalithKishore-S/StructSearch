from pathlib import Path

import numpy as np
import pytest

from structsearch.indexing import BM25Index, build_index, build_text_records
from structsearch.ingestion import ingest_corpus, split_source
from structsearch.schemas import TextRecord

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def units():
    return ingest_corpus(CORPUS).units


@pytest.fixture(scope="module")
def index(units):
    return build_index(units)


def _top(index, query, k=3):
    return [h.unit_id for h in index.search(query, k)]


# ---- acceptance queries ----

def test_read_file_ranks_file_readers_first(index):
    assert set(_top(index, "read file", 2)) == {
        "files.py::read_config_safe",
        "files.py::read_lines",
    }


def test_recursive_tree_traversal(index):
    assert _top(index, "recursive tree traversal", 1) == ["trees.py::inorder_traverse"]


def test_other_queries(index):
    assert _top(index, "convert camel case to snake case", 1) == ["utils.py::camel_to_snake"]
    assert _top(index, "factorial", 1) == ["trees.py::factorial"]
    assert "db.py::validate_user_input" in _top(index, "validate user input", 2)


def test_class_name_in_query_finds_method(index):
    assert _top(index, "Counter increment", 1) == ["utils.py::Counter.increment"]


def test_failed_file_is_searchable(index):
    assert _top(index, "broken syntax", 1) == ["broken_syntax.py::<module>"]


# ---- scoring behaviour ----

def test_name_match_outweighs_body_match(index):
    hits = index.search("add", 3)
    assert hits[0].unit_id == "utils.py::add"


def test_hits_report_weighted_field_contributions(index):
    hit = index.search("read file", 1)[0]
    assert pytest.approx(sum(hit.field_scores.values())) == hit.score
    assert hit.field_scores["name"] > 0


def test_explain_lists_matched_terms(index):
    matched = index.explain("read file", "files.py::read_lines")
    assert matched["name"] == ["read"]
    assert matched["doc"] == ["file", "read"]


def test_only_positive_scores_returned_and_k_respected(index):
    assert index.search("zzzzqqqq", 5) == []
    assert index.search("", 5) == []
    assert index.search("find all the functions", 5) == []
    assert len(index.search("file", 2)) == 2


def test_ties_broken_by_unit_id():
    recs = [
        TextRecord(unit_id="b.py::f", name="same"),
        TextRecord(unit_id="a.py::f", name="same"),
    ]
    idx = BM25Index.build(recs)
    assert [h.unit_id for h in idx.search("same")] == ["a.py::f", "b.py::f"]


def test_score_all_aligned_with_unit_ids(index):
    scores = index.score_all("read file")
    assert len(scores) == len(index.unit_ids)
    best = index.unit_ids[int(np.argmax(scores))]
    assert best == index.search("read file", 1)[0].unit_id


def test_field_weights_change_ranking(units):
    records = build_text_records(units)
    name_heavy = BM25Index.build(records, {"name": 10, "identifiers": 0, "doc": 0, "code": 0})
    doc_only = BM25Index.build(records, {"name": 0, "identifiers": 0, "doc": 1, "code": 0})
    assert name_heavy.search("add", 1)[0].unit_id == "utils.py::add"
    assert doc_only.search("add", 5)[0].field_scores.keys() == {"doc"}


# ---- edge cases ----

def test_empty_index():
    idx = BM25Index.build([])
    assert idx.search("anything") == [] and len(idx.score_all("x")) == 0


def test_corpus_without_docstrings_or_comments_does_not_crash():
    units = split_source("def alpha():\n    return 1\n\ndef beta():\n    return 2\n", "m.py")
    idx = build_index(units)
    assert [h.unit_id for h in idx.search("alpha")] == ["m.py::alpha"]


# ---- persistence ----

def test_save_load_gives_identical_scores(index, tmp_path):
    path = tmp_path / "idx" / "bm25_index.json"
    index.save(path)
    loaded = BM25Index.load(path)
    assert loaded.unit_ids == index.unit_ids
    for query in ["read file", "recursive tree traversal", "validate user input", "xyz"]:
        assert np.array_equal(loaded.score_all(query), index.score_all(query))
        assert loaded.search(query, 5) == index.search(query, 5)
    assert loaded.field_weights == index.field_weights


def test_load_rejects_unknown_version(index, tmp_path):
    path = tmp_path / "bm25_index.json"
    index.save(path)
    path.write_text(path.read_text().replace('"version":1', '"version":99'))
    with pytest.raises(ValueError):
        BM25Index.load(path)
