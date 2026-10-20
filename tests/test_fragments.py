import ast
import json
import textwrap
from pathlib import Path

import pytest

from structsearch.ingestion import ingest_corpus, split_source
from structsearch.parsing import (
    FRAGMENT_FILE,
    FRAGMENT_VERSION,
    FragmentRecord,
    describe_term,
    ensure_fragment_records,
    extract_all_fragments,
    extract_fragments,
    fragment_terms,
    load_fragment_records,
    save_fragment_records,
    snippet_terms,
)
from structsearch.parsing.fragments import canonical_base, canonical_specific, node_labels

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def terms(source):
    unit = split_source(textwrap.dedent(source), "m.py")[0]
    return extract_fragments(unit).terms


# ---- labels ----

def labels_of(code):
    return node_labels(ast.parse(code).body[0].value if isinstance(ast.parse(code).body[0], ast.Expr) else ast.parse(code).body[0])


def test_call_labels_name_and_dotted_name():
    assert labels_of("open(p)") == ["Call", "Call:open"]
    assert labels_of("os.system(c)") == ["Call", "Call:system", "Call:os.system"]
    assert labels_of("a.b.c.d(x)") == ["Call", "Call:d"]  # too deep to be a useful dotted label
    assert labels_of("self.walk(n)") == ["Call", "Call:walk"]  # self./cls. add nothing
    assert labels_of("f()()") == ["Call"]


def test_other_labels():
    assert labels_of("x = a + b") == ["Assign"]
    assert node_labels(ast.parse("a + b").body[0].value) == ["BinOp", "BinOp:Add"]
    assert node_labels(ast.parse("a % b").body[0].value) == ["BinOp", "BinOp:Mod"]
    assert node_labels(ast.parse("not a").body[0].value) == ["UnaryOp", "UnaryOp:Not"]
    assert node_labels(ast.parse("f'{a}'").body[0].value) == ["JoinedStr"]
    handler = ast.parse("try:\n pass\nexcept (A, b.B):\n pass\nexcept:\n pass").body[0].handlers
    assert node_labels(handler[0]) == ["ExceptHandler", "ExceptHandler:A", "ExceptHandler:B"]
    assert node_labels(handler[1]) == ["ExceptHandler", "ExceptHandler:bare"]
    assert node_labels(ast.parse("raise ValueError('x')").body[0]) == ["Raise", "Raise:ValueError"]
    assert node_labels(ast.parse("raise").body[0]) == ["Raise"]
    assert node_labels(ast.parse("x").body[0].value) == []  # names are transparent


def test_async_variants_fold_into_sync_labels():
    t = terms("""
    async def f(xs):
        async for x in xs:
            async with lock:
                await go(x)
    """)
    assert "ad:For//With" in t and "u:For" in t and "u:With" in t and "u:Await" in t


def test_canonical_helpers():
    assert canonical_base("for") == "For" and canonical_base("nope") is None
    assert canonical_specific("BinOp", "add") == "Add" and canonical_specific("BinOp", "plus") is None
    assert canonical_specific("Call", "os.path.join") == "os.path.join"
    assert canonical_specific("Call", "bad name") is None and canonical_specific("If", "x") is None


# ---- containment, children, order ----

def test_try_inside_loop_differs_from_try_next_to_loop():
    inside = terms("""
    def f(xs):
        for x in xs:
            try:
                run(x)
            except Exception:
                pass
    """)
    beside = terms("""
    def f(xs):
        for x in xs:
            run(x)
        try:
            run(1)
        except Exception:
            pass
    """)
    assert "ad:For//Try" in inside and "pc:For>Try" in inside
    assert "ad:For//Try" not in beside and "ord:For=>Try" in beside
    assert "ord:For=>Try" not in inside  # the loop contains the try, it does not precede it


def test_direct_child_vs_deeper_descendant():
    t = terms("""
    def f(x):
        for i in x:
            if i:
                try:
                    pass
                except E:
                    pass
    """)
    assert "pc:For>If" in t and "pc:If>Try" in t and "pc:For>Try" not in t
    assert "ad:For//Try" in t and "ch3:For>If>Try" in t


def test_open_inside_and_outside_with():
    good = terms("def f(p):\n    with open(p) as h:\n        return h.read()\n")
    bad = terms("def f(p):\n    h = open(p)\n    return h.read()\n")
    assert "ad:With//Call:open" in good and "ad:With//Call:open" not in bad
    assert "u:Call:open" in bad


def test_guard_before_call_is_ordering_not_containment():
    guarded = terms("""
    def f(x, db):
        if not x:
            raise ValueError()
        return db.execute(x)
    """)
    unguarded = terms("""
    def f(x, db):
        r = db.execute(x)
        if not r:
            raise ValueError()
        return r
    """)
    assert "ord:If=>Call:execute" in guarded and "ord:Raise=>Call:execute" in guarded
    assert "ord:If=>Call:execute" not in unguarded and "ord:Call:execute=>If" in unguarded
    assert "ad:If//Call:execute" not in guarded


def test_string_building_inside_and_before_execute():
    before = terms("def f(db, a):\n    q = 'x' + a\n    return db.execute(q)\n")
    inside = terms("def f(db, a):\n    return db.execute('x' + a)\n")
    assert "ord:BinOp:Add=>Call:execute" in before and "ad:Call:execute//BinOp:Add" not in before
    assert "ad:Call:execute//BinOp:Add" in inside and "ord:BinOp:Add=>Call:execute" not in inside


def test_root_function_is_not_labelled_but_nested_defs_are():
    t = terms("def outer():\n    def inner():\n        return 1\n    return inner\n")
    assert "u:FunctionDef" in t and t["u:FunctionDef"] == 1  # only the inner one
    assert "ad:FunctionDef//Return" in t


def test_counts_for_u_pc_and_presence_for_ad_ord():
    t = terms("def f(a):\n    if a:\n        return 1\n    if not a:\n        return 2\n    return 3\n")
    assert t["u:If"] == 2 and t["u:Return"] == 3 and t["pc:If>Return"] == 2
    assert t["ad:If//Return"] == 1 and t["ord:If=>Return"] == 1


def test_raise_and_except_specifics():
    t = terms("""
    def f():
        try:
            go()
        except ValueError:
            raise RuntimeError("x")
        except:
            pass
    """)
    assert "ad:ExceptHandler:ValueError//Raise:RuntimeError" in t
    assert "pc:ExceptHandler:bare>Pass" in t and "ad:Try//ExceptHandler:bare" in t


def test_ordering_is_capped_for_huge_functions():
    body = "\n".join(f"    f{i}(x)" for i in range(700))
    t = terms(f"def big(x):\n{body}\n")
    assert t["u:Call"] == 700
    assert "ord:Call:f0=>Call:f1" in t and "ord:Call:f650=>Call:f651" not in t  # beyond MAX_ORD_NODES


def test_deterministic_and_does_not_change_unit():
    units = ingest_corpus(CORPUS).units
    before = [u.source_text for u in units]
    assert extract_all_fragments(units) == extract_all_fragments(units)
    assert before == [u.source_text for u in units]


def test_failed_file_unit_has_empty_fragments():
    units = {u.unit_id: u for u in ingest_corpus(CORPUS).units}
    rec = extract_fragments(units["broken_syntax.py::<module>"])
    assert rec.parse_status == "failed" and rec.terms == {} and rec.extraction_version == FRAGMENT_VERSION


def test_every_term_has_a_known_kind_and_describes_itself():
    for unit in ingest_corpus(CORPUS).units:
        for term in extract_fragments(unit).terms:
            assert term.split(":", 1)[0] in ("u", "pc", "ch3", "ad", "ord")
            assert describe_term(term)
    assert describe_term("ad:For//Try") == "For contains Try"
    assert describe_term("ord:If=>Call:execute") == "If before Call:execute"
    assert describe_term("pc:Try>ExceptHandler") == "Try has child ExceptHandler"
    assert describe_term("u:Call:open") == "has Call:open"
    assert describe_term("ch3:For>If>Try") == "For > If > Try"


# ---- snippets ----

def test_snippet_function_statements_and_indentation():
    func = snippet_terms("def anything(x):\n    for i in x:\n        try:\n            go(i)\n        except E:\n            pass\n")
    loose = snippet_terms("for i in x:\n    try:\n        go(i)\n    except E:\n        pass\n")
    indented = snippet_terms("    for i in x:\n        try:\n            go(i)\n        except E:\n            pass\n")
    assert func == loose == indented and "ad:For//Try" in func


def test_snippet_with_return_outside_function_still_parses():
    assert "u:Return" in snippet_terms("x = a + b\nreturn x\n")


def test_snippet_errors():
    for bad in ("", "   \n", "def (:", "for for for"):
        with pytest.raises(ValueError):
            snippet_terms(bad)


# ---- record and store ----

def test_record_roundtrip_and_equality():
    rec = FragmentRecord("a::f", {"u:If": 2, "ad:For//Try": 1})
    assert FragmentRecord.from_dict(json.loads(json.dumps(rec.to_dict()))) == rec
    assert rec != FragmentRecord("a::f", {"u:If": 1})


def test_store_roundtrip_missing_corrupt_and_old(tmp_path):
    records = extract_all_fragments(ingest_corpus(CORPUS).units)
    save_fragment_records(records, tmp_path / FRAGMENT_FILE, "fp")
    assert load_fragment_records(tmp_path / FRAGMENT_FILE) == ("fp", records)
    assert load_fragment_records(tmp_path / "missing.jsonl") is None
    (tmp_path / "bad.jsonl").write_text("nope\n")
    assert load_fragment_records(tmp_path / "bad.jsonl") is None
    (tmp_path / "old.jsonl").write_text('{"_meta": {"extraction_version": "0", "fingerprint": "x"}}\n')
    assert load_fragment_records(tmp_path / "old.jsonl") is None
    (tmp_path / "trunc.jsonl").write_text('{"_meta": {"extraction_version": "%s", "fingerprint": "x"}}\n{"unit_id": 1}\n' % FRAGMENT_VERSION)
    assert load_fragment_records(tmp_path / "trunc.jsonl") is None


def test_ensure_fragment_records_lifecycle(tmp_path):
    units = ingest_corpus(CORPUS).units
    records, reason = ensure_fragment_records(units, tmp_path)
    assert reason == "no fragment index yet" and [r.unit_id for r in records] == [u.unit_id for u in units]
    again, reason = ensure_fragment_records(units, tmp_path)
    assert reason is None and again == records
    units[3].source_text += "\n# edited"
    assert ensure_fragment_records(units, tmp_path)[1] == "units changed"
    assert ensure_fragment_records(units[:4], tmp_path)[1] == "units changed"
