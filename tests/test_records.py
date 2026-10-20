from pathlib import Path

from structsearch.indexing import build_text_record, build_text_records
from structsearch.ingestion import ingest_corpus, split_source

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def _records():
    return {r.unit_id: r for r in build_text_records(ingest_corpus(CORPUS).units)}


def test_function_record_fields():
    rec = _records()["db.py::get_user"]
    assert rec.name == "get_user"
    for ident in ("validate_user_input", "db", "execute", "username", "clean", "fetchone"):
        assert ident in rec.identifiers
    assert "def" not in rec.identifiers and "return" not in rec.identifiers
    assert "Validate the username" in rec.docstring_comments
    assert "SELECT" in rec.code_tokens and "def" in rec.code_tokens


def test_method_name_is_qualified():
    assert _records()["utils.py::Counter.increment"].name == "Counter.increment"


def test_comments_are_extracted():
    src = "def f(x):\n    # check the input first\n    return x  # trailing note\n"
    rec = build_text_record(split_source(src, "m.py")[0])
    assert "check the input first" in rec.docstring_comments
    assert "trailing note" in rec.docstring_comments


def test_duplicate_suffix_removed_from_name():
    src = (
        "class A:\n    @property\n    def x(self):\n        return 1\n"
        "    @x.setter\n    def x(self, v):\n        pass\n"
    )
    names = [build_text_record(u).name for u in split_source(src, "m.py")]
    assert names == ["A.x", "A.x"]


def test_failed_file_record_uses_regex_fallback():
    rec = _records()["broken_syntax.py::<module>"]
    assert rec.name == "broken_syntax"
    assert "broken_function" in rec.identifiers
    assert "def" not in rec.identifiers


def test_method_source_indentation_does_not_break_comment_extraction():
    src = "class A:\n    def m(self):\n        # note inside method\n        return 1\n"
    rec = build_text_record(split_source(src, "m.py")[0])
    assert "note inside method" in rec.docstring_comments
