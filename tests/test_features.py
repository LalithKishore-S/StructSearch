import ast
import textwrap
from pathlib import Path

import pytest

from structsearch.ingestion import ingest_corpus, split_source
from structsearch.parsing import (
    FEATURE_DOC,
    FEATURE_NAMES,
    NODE_PREFIX,
    extract_all,
    extract_features,
    get_feature,
    node_type_counts,
)

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def feats(source, path="m.py", index=0):
    """Features of the index-th unit found in a source snippet."""
    unit = split_source(textwrap.dedent(source), path)[index]
    return extract_features(unit).features


@pytest.fixture(scope="module")
def fixture_features():
    return {u.unit_id: extract_features(u).features for u in ingest_corpus(CORPUS).units if u.parse_status == "ok"}


# ---- fixture corpus (known answers) ----

def test_recursive_fixtures_have_self_call(fixture_features):
    assert fixture_features["trees.py::inorder_traverse"]["self_call"] == 1
    assert fixture_features["trees.py::inorder_traverse"]["self_call_count"] == 2
    assert fixture_features["trees.py::factorial"]["self_call"] == 1
    # iterative traversal: no self call even though it is about trees
    count_nodes = fixture_features["trees.py::count_nodes"]
    assert count_nodes["self_call"] == 0 and count_nodes["while_count"] == 1
    assert count_nodes["max_depth"] == 2 and count_nodes["max_loop_depth"] == 1


def test_exception_handling_fixture(fixture_features):
    f = fixture_features["files.py::read_config_safe"]
    assert (f["try_count"], f["except_count"], f["with_count"]) == (1, 2, 1)
    assert f["try_with_handler_count"] == 1 and f["call_in_try_count"] == 2
    assert f["bare_except_count"] == 0 and f["return_count"] == 3
    # same file access without error handling
    g = fixture_features["files.py::read_lines"]
    assert g["try_count"] == 0 and g["with_count"] == 1


def test_validation_fixture(fixture_features):
    v = fixture_features["db.py::validate_user_input"]
    assert v["if_count"] == 2 and v["raise_count"] == 2
    assert v["guard_clause_count"] == 2 and v["raise_in_if_count"] == 2
    assert v["type_check_count"] == 1 and v["return_count"] == 1
    gu = fixture_features["db.py::get_user"]
    assert gu["call_count"] == 3 and gu["guard_clause_count"] == 0
    assert fixture_features["db.py::find_user_unsafe"]["if_count"] == 0


def test_method_in_class_and_all_features_present(fixture_features):
    inc = fixture_features["utils.py::Counter.increment"]
    assert inc["arg_count"] == 2 and inc["self_call"] == 0
    for unit_id, f in fixture_features.items():
        for name in FEATURE_NAMES:
            assert name in f and isinstance(f[name], float), (unit_id, name)


def test_failed_file_unit_has_no_features():
    units = {u.unit_id: u for u in ingest_corpus(CORPUS).units}
    rec = extract_features(units["broken_syntax.py::<module>"])
    assert rec.parse_status == "failed" and rec.features == {} and rec.extraction_version == "1"


# ---- recursion ----

def test_method_self_calls():
    src = """
    class Tree:
        def walk(self, n):
            self.walk(n.left)
            Tree.walk(self, n.right)
            cls_walk = walk(n)        # bare name: refers to a global, not the method
            super().walk(n)           # parent implementation, not recursion
    """
    f = feats(src)
    assert f["self_call"] == 1 and f["self_call_count"] == 2


def test_bare_call_in_method_is_not_recursion_and_function_name_clash():
    src = """
    class A:
        def count(self):
            return count(3)
    def other():
        return other()
    """
    assert feats(src, index=0)["self_call"] == 0
    assert feats(src, index=1)["self_call"] == 1


def test_mutual_recursion_is_not_a_self_call():
    src = """
    def even(n):
        return n == 0 or odd(n - 1)
    """
    assert feats(src)["self_call"] == 0


# ---- nesting depth ----

def test_depth_counts_nesting_and_elif_is_flat():
    src = """
    def f(x):
        if x:
            for i in x:
                try:
                    pass
                except Exception:
                    pass
        elif x is None:
            pass
        elif x == 3:
            pass
        else:
            pass
    """
    f = feats(src)
    assert f["max_depth"] == 3 and f["max_loop_depth"] == 1
    assert f["if_count"] == 3  # if + two elifs


def test_flat_chain_has_depth_one_and_no_control_zero():
    chain = feats("def f(x):\n    if x == 1:\n        pass\n    elif x == 2:\n        pass\n    elif x == 3:\n        pass\n")
    assert chain["max_depth"] == 1
    assert feats("def f():\n    return 1\n")["max_depth"] == 0


def test_nested_loops_and_with():
    src = """
    def f(rows):
        with open("x") as h:
            for r in rows:
                while r:
                    r -= 1
    """
    f = feats(src)
    assert f["max_depth"] == 3 and f["max_loop_depth"] == 2 and f["with_count"] == 1


# ---- other constructs ----

def test_async_generator_lambda_comprehension_nested_def():
    src = """
    @decorator
    @other(1)
    async def f(a, /, b, *args, c=1, **kw):
        x = [i for i in a]
        y = {k: v for k, v in b}
        g = (i for i in a)
        h = lambda z: z
        def inner():
            yield 1
        await something()
        yield x
    """
    f = feats(src)
    assert f["is_async"] == 1 and f["is_generator"] == 1 and f["yield_count"] == 2
    assert f["await_count"] == 1 and f["comprehension_count"] == 3 and f["lambda_count"] == 1
    assert f["nested_def_count"] == 1 and f["decorator_count"] == 2
    assert f["arg_count"] == 5  # a, b, *args, c, **kw


def test_bare_except_finally_assert_and_raise_outside_if():
    src = """
    def f():
        try:
            risky()
        except:
            raise
        finally:
            cleanup()
        assert True
    """
    f = feats(src)
    assert f["bare_except_count"] == 1 and f["finally_count"] == 1 and f["assert_count"] == 1
    assert f["raise_count"] == 1 and f["raise_in_if_count"] == 0
    assert f["call_in_try_count"] == 1  # risky(), not cleanup()


def test_calls_unique_names_and_type_checks():
    f = feats("def f(x):\n    a.b(x)\n    c.b(x)\n    isinstance(x, int)\n    issubclass(x, int)\n    d()()\n")
    assert f["call_count"] == 6  # d()() is two Call nodes
    assert f["unique_call_count"] == 4  # b, isinstance, issubclass, d (the outer call has no name)
    assert f["type_check_count"] == 2


def test_guard_clause_only_at_top_level_of_body():
    src = """
    def f(x):
        if not x:
            return None
        if x < 0:
            raise ValueError()
        if x == 1:
            print(x)
        for i in x:
            if i:
                return i
    """
    assert feats(src)["guard_clause_count"] == 2


def test_match_statement_counted_when_supported():
    if not hasattr(ast, "Match"):
        pytest.skip("match needs Python 3.10+")
    src = "def f(x):\n    match x:\n        case 1:\n            return 1\n        case _:\n            return 2\n"
    f = feats(src)
    assert f["match_count"] == 1 and f["max_depth"] == 1


# ---- histogram and counts ----

def test_node_histogram_and_count_consistency():
    unit = split_source("def f(a):\n    if a:\n        return g(a)\n    return None\n", "m.py")[0]
    rec = extract_features(unit)
    node = ast.parse(unit.source_text).body[0]
    walked = [n for n in ast.walk(node) if not isinstance(n, ast.expr_context)]
    assert rec.features["node_count"] == len(walked)
    types = node_type_counts(rec)
    assert types["If"] == 1 and types["Return"] == 2 and types["Call"] == 1
    assert "Load" not in types and sum(types.values()) == len(walked)
    assert all(k.startswith(NODE_PREFIX) for k in rec.features if k not in FEATURE_NAMES)
    assert get_feature(rec, "node:Nonexistent") == 0.0 and get_feature(rec, "if_count") == 1.0


def test_line_count_and_feature_doc():
    unit = split_source("def f():\n    a = 1\n    return a\n", "m.py")[0]
    assert extract_features(unit).features["line_count"] == 3
    assert set(FEATURE_DOC) == set(FEATURE_NAMES) and all(FEATURE_DOC.values())


def test_deeply_nested_expression_does_not_overflow_the_stack():
    expr = " + ".join(["x"] * 3000)
    try:
        unit = split_source(f"def f(x):\n    return {expr}\n", "m.py")
    except RecursionError:  # some Python versions refuse to parse this at all
        pytest.skip("parser rejected the input")
    assert extract_features(unit[0]).features["node_count"] > 3000


def test_extraction_is_deterministic_and_does_not_change_the_unit():
    units = ingest_corpus(CORPUS).units
    before = [u.source_text for u in units]
    assert [r.to_dict() for r in extract_all(units)] == [r.to_dict() for r in extract_all(units)]
    assert before == [u.source_text for u in units]
