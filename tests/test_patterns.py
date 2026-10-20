from dataclasses import replace
from pathlib import Path

import pytest

from structsearch.ingestion import ingest_corpus
from structsearch.llm import LLMError, LLMSettings
from structsearch.parsing import extract_all, extract_all_fragments
from structsearch.retrieval.patterns import (
    MAX_ATOMS,
    Atom,
    PatternError,
    holds,
    parse_pattern,
    parse_patterns,
    witnesses,
)
from structsearch.retrieval.structural import (
    SQL_BUILT_PATTERN,
    Constraint,
    ConstraintProfile,
    build_profile,
    llm_prompt,
    llm_schema,
    match_unit,
    parse_llm_output,
    parse_llm_patterns,
    rules_profile,
    structural_scores,
    structural_search,
)

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def corpus():
    result = ingest_corpus(CORPUS)
    units = {u.unit_id: u for u in result.units}
    return units, extract_all(result.units), extract_all_fragments(result.units)


def matching(corpus, pattern):
    units, _, fragments = corpus
    relation = parse_pattern(pattern)
    return {f.unit_id for f in fragments if f.terms and holds(relation, f.terms)}


# ---- parsing ----

@pytest.mark.parametrize(
    "text, canonical, n_atoms, negate",
    [
        ("Call:open", "Call:open", 1, False),
        ("for//try", "For//Try", 1, False),
        ("For|While//Try", "For|While//Try", 2, False),
        ("For|While // Try|With", "For|While//Try|With", 4, False),
        ("!With//Call:open", "!With//Call:open", 1, True),
        ("not With//Call:open", "!With//Call:open", 1, True),
        ("If=>Call:execute", "If=>Call:execute", 1, False),
        ("Try>ExceptHandler:bare", "Try>ExceptHandler:bare", 1, False),
        ("BinOp:add=>Call:execute", "BinOp:Add=>Call:execute", 1, False),
        ("Call:execute//BinOp:Add or BinOp:Add=>Call:execute", "Call:execute//BinOp:Add or BinOp:Add=>Call:execute", 2, False),
        ("  For // Try  ", "For//Try", 1, False),
        ("For|For//Try", "For//Try", 1, False),  # duplicate alternatives collapse
        ("Call:open or Call:open", "Call:open", 1, False),
        ("Call:open and !With//Call:open", "Call:open and !With//Call:open", 2, False),
        ("Call:open  and  not With//Call:open", "Call:open and !With//Call:open", 2, False),
        ("Call:open and Call:open", "Call:open", 1, False),
    ],
)
def test_parse_valid_patterns(text, canonical, n_atoms, negate):
    relation = parse_pattern(text)
    assert relation.text == canonical and len(relation.atoms) == n_atoms and relation.clauses[0].negate is negate
    assert parse_pattern(relation.text).text == relation.text  # canonical form is stable


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("Foo//Try", "unknown label 'Foo'"),
        ("Name", "unknown label"),
        ("For//", "empty label"),
        ("//Try", "empty label"),
        ("If:x", "no ':' variants"),
        ("BinOp:plus", "not valid after"),
        ("Call:a b", "not valid after"),
        ("Call:", "not valid after"),
        ("A//B//C", "one operator"),
        ("For//Try=>If", "one operator"),
        ("Try>>If", "one operator"),
        ("Name=>If", "unknown label"),
        ("Compare=>If", "ordering-relevant"),
        ("If=>Pass", "ordering-relevant"),
        ("x" * 400, "too long"),
    ],
)
def test_parse_invalid_patterns(text, message):
    with pytest.raises(PatternError, match=message):
        parse_pattern(text)


def test_parse_pattern_rejects_non_strings_and_huge_expansions():
    with pytest.raises(PatternError):
        parse_pattern(None)
    with pytest.raises(PatternError, match="too many"):
        parse_pattern("|".join(["Call:a%d" % i for i in range(9)]) + "//" + "|".join(["Call:b%d" % i for i in range(9)]))
    assert MAX_ATOMS == 64
    assert [r.text for r in parse_patterns(["For//Try", "Call:open"])] == ["For//Try", "Call:open"]


def test_atom_terms():
    assert Atom("has", "Call:open").term == "u:Call:open"
    assert Atom("contains", "For", "Try").term == "ad:For//Try"
    assert Atom("child", "Try", "ExceptHandler").term == "pc:Try>ExceptHandler"
    assert Atom("before", "If", "Call").term == "ord:If=>Call"


def test_and_clauses_must_all_hold():
    both = parse_pattern("Call:open and !With//Call:open")
    assert holds(both, {"u:Call:open": 1})
    assert not holds(both, {"u:Call:open": 1, "ad:With//Call:open": 1})  # opened inside a with
    assert not holds(both, {})  # never opens a file
    assert witnesses(both, {"u:Call:open": 1}) == ["u:Call:open"]
    mixed = parse_pattern("For|While//Try and Call:log or Call:print")
    assert holds(mixed, {"ad:For//Try": 1, "u:Call:print": 1}) and not holds(mixed, {"ad:For//Try": 1})


def test_holds_and_witnesses():
    terms = {"ad:For//Try": 1, "u:Call:open": 2}
    either = parse_pattern("For|While//Try")
    assert holds(either, terms) and witnesses(either, terms) == ["ad:For//Try"]
    negated = parse_pattern("!For//Try")
    assert not holds(negated, terms) and witnesses(negated, terms) == []
    assert holds(parse_pattern("!With//Call:open"), terms)
    assert not holds(parse_pattern("With//Call:open"), {})


# ---- matching real fixture functions ----

def test_open_outside_with_matches_nothing_in_fixtures(corpus):
    assert matching(corpus, "Call:open and !With//Call:open") == set()  # every open() is inside a with


def test_with_open_pattern_on_fixtures(corpus):
    assert matching(corpus, "With//Call:open") == {
        "files.py::read_config_safe", "files.py::write_log", "files.py::read_lines"}
    assert matching(corpus, "Call:open") == matching(corpus, "With//Call:open")  # every open() is in a with
    assert matching(corpus, "!With//Call:open") - matching(corpus, "With//Call:open") != set()


def test_sql_patterns_separate_unsafe_from_parameterized(corpus):
    assert matching(corpus, "BinOp:Add=>Call:execute") == {"db.py::find_user_unsafe"}
    assert matching(corpus, "Call:execute//BinOp:Add") == {"db.py::count_rows"}
    built = matching(corpus, SQL_BUILT_PATTERN)
    assert built == {"db.py::find_user_unsafe", "db.py::count_rows"}
    assert "db.py::get_user" not in built  # parameterized query


def test_try_structure_patterns(corpus):
    assert matching(corpus, "Try>ExceptHandler") == {"files.py::read_config_safe"}
    assert matching(corpus, "Try//With") == {"files.py::read_config_safe"}
    assert matching(corpus, "For|While//Try") == set()


def test_guard_before_work_pattern(corpus):
    assert "db.py::validate_user_input" in matching(corpus, "If=>Return")
    assert matching(corpus, "Raise:ValueError") >= {"db.py::validate_user_input"}


# ---- relations inside the profile score ----

def test_match_unit_mixes_constraints_and_relations():
    profile = ConstraintProfile(
        (Constraint(("self_call",), "present"),),
        relations=(parse_pattern("For//Try"), parse_pattern("!With//Call:open")),
    )
    all_ok = match_unit(profile, {"self_call": 1.0}, {"ad:For//Try": 1})
    assert all_ok.score == 1.0 and len(all_ok.matched) == 3 and all_ok.witness_terms == ["ad:For//Try"]
    one_miss = match_unit(profile, {"self_call": 1.0}, {})
    assert one_miss.score == pytest.approx(2 / 3) and len(one_miss.missed) == 1
    no_terms = match_unit(profile, {"self_call": 1.0})  # patterns cannot be checked: unmet
    assert no_terms.score == pytest.approx(1 / 3)


def test_relation_weight_and_empty_profile_with_only_relations():
    heavy = replace(parse_pattern("For//Try"), weight=3.0)
    profile = ConstraintProfile((Constraint(("self_call",), "present"),), relations=(heavy,))
    assert match_unit(profile, {"self_call": 1.0}, {}).score == pytest.approx(0.25)
    only = ConstraintProfile(relations=(parse_pattern("Call:open"),))
    assert not only.is_empty and match_unit(only, {}, {"u:Call:open": 1}).score == 1.0


def test_structural_search_uses_patterns_and_explains(corpus):
    units, records, fragments = corpus
    profile = ConstraintProfile(relations=(parse_pattern(SQL_BUILT_PATTERN).with_reason("SQL built by string formatting"),))
    results = structural_search(profile, units, records, k=10, fragments=fragments)
    assert {r.unit_id for r in results} == {"db.py::find_user_unsafe", "db.py::count_rows"}
    unsafe = next(r for r in results if r.unit_id == "db.py::find_user_unsafe")
    assert any("structural match: SQL built by string formatting [pattern:" in line for line in unsafe.evidence)
    assert any(line.startswith("structure found:") and "BinOp:Add before Call:execute" in line for line in unsafe.evidence)
    assert structural_search(profile, units, records, k=10) == []  # no fragments: patterns cannot match
    scores = structural_scores(profile, records, fragments)
    assert scores["db.py::get_user"] == 0.0 and scores["db.py::find_user_unsafe"] == 1.0
    assert scores["broken_syntax.py::<module>"] == 0.0


def test_negated_pattern_alone_matches_everything_without_the_structure(corpus):
    units, records, fragments = corpus
    profile = ConstraintProfile(relations=(parse_pattern("!With//Call:open"),))
    ids = {r.unit_id for r in structural_search(profile, units, records, k=50, fragments=fragments)}
    assert "files.py::read_lines" not in ids and "db.py::get_user" in ids
    assert "broken_syntax.py::<module>" not in ids


def test_with_relations_merges_without_duplicates():
    base = rules_profile("recursive")
    merged = base.with_relations([parse_pattern("For//Try"), parse_pattern("for//try")])
    assert len(merged.relations) == 1 and merged.constraints == base.constraints
    assert merged.with_relations([parse_pattern("Call:open")]).relations[1].text == "Call:open"
    assert "For//Try" in merged.describe()
    assert merged.to_dict()["patterns"][0]["pattern"] == "For//Try"


# ---- rule-based mapping to patterns ----

def pats(query):
    return [r.text for r in rules_profile(query).relations]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("try except inside a loop", ["For|While//Try"]),
        ("error handling within each loop", ["For|While//Try"]),
        ("a loop containing a try block", ["For|While//Try"]),
        ("exception handling inside a for loop", ["For|While//Try"]),
        ("read a file without a context manager", ["Call:open and !With//Call:open"]),
        ("unclosed files", ["Call:open and !With//Call:open"]),
        ("opens a file using a with statement", ["With//Call:open"]),
        ("sql injection", [SQL_BUILT_PATTERN]),
        ("query built with string concatenation", [SQL_BUILT_PATTERN]),
        ("unparameterized queries", [SQL_BUILT_PATTERN]),
        ("parameterized queries", ["Call:execute|Call:executemany|Call:executescript and !" + SQL_BUILT_PATTERN]),
        ("calls eval", ["Call:eval|Call:exec"]),
        ("returns inside a loop", ["For|While//Return"]),
        ("parse a csv", []),
        ("recursive", []),
    ],
)
def test_rules_map_phrases_to_patterns(query, expected):
    assert pats(query) == expected


def test_rules_negate_patterns():
    assert pats("no sql injection") == ["!" + SQL_BUILT_PATTERN]
    assert pats("not using eval") == ["!Call:eval|Call:exec"]
    assert pats("without error handling inside a loop") == ["!For|While//Try"]


def test_constraints_and_patterns_coexist_and_pattern_words_are_not_counted_twice():
    profile = rules_profile("recursive function with error handling inside a loop")
    assert [c.reason for c in profile.constraints] == ["recursion"]  # 'error handling' consumed by the pattern
    assert len(profile.relations) == 1


def test_rule_patterns_all_parse_and_reasons_are_human():
    for query in ("try in a loop", "open a file without with", "sql injection", "eval", "return in a loop"):
        for relation in rules_profile(query).relations:
            assert relation.reason and relation.reason != relation.text


# ---- LLM patterns ----

def test_llm_schema_and_prompt_describe_patterns():
    schema = llm_schema()
    assert schema["properties"]["patterns"]["items"]["type"] == "string" and schema["required"] == ["constraints"]
    prompt = llm_prompt("x")
    for needle in ("A // B", "A => B", "!pattern", "Call:open", "ExceptHandler:bare", "'X without Y'"):
        assert needle in prompt


def test_parse_llm_patterns_validation():
    good = parse_llm_patterns({"patterns": ["For//Try", "!With//Call:open", "for//try"]})
    assert [r.text for r in good] == ["For//Try", "!With//Call:open"]
    assert [r.text for r in parse_llm_patterns({"patterns": ["Nope//Try", "Call:open", 7]})] == ["Call:open"]
    assert parse_llm_patterns({"constraints": []}) == [] and parse_llm_patterns({"patterns": []}) == []
    with pytest.raises(ValueError):
        parse_llm_patterns({"patterns": ["Nope//Try", ""]})
    with pytest.raises(ValueError):
        parse_llm_patterns({"patterns": "For//Try"})


def test_parse_llm_output_combinations():
    c, r = parse_llm_output({"constraints": [{"features": ["self_call"], "op": "present"}], "patterns": ["For//Try"]})
    assert len(c) == 1 and len(r) == 1
    c, r = parse_llm_output({"patterns": ["Call:open"]})  # patterns only
    assert c == [] and [x.text for x in r] == ["Call:open"]
    c, r = parse_llm_output({"constraints": [{"features": ["self_call"], "op": "present"}], "patterns": ["Bad//Try"]})
    assert len(c) == 1 and r == []  # bad pattern dropped, good constraint kept
    c, r = parse_llm_output({"constraints": [{"features": ["nope"], "op": "present"}], "patterns": ["Call:open"]})
    assert c == [] and len(r) == 1
    assert parse_llm_output({"constraints": [], "patterns": []}) == ([], [])
    with pytest.raises(ValueError):
        parse_llm_output({"constraints": [{"features": ["nope"], "op": "present"}], "patterns": ["Bad//Try"]})
    with pytest.raises(ValueError):
        parse_llm_output({"constraints": [], "patterns": ["Bad//Try"]})


class Stub:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def generate_json(self, prompt, schema=None):
        if self.error:
            raise self.error
        return self.reply


def test_build_profile_takes_patterns_from_the_model():
    reply = {"constraints": [], "patterns": ["Call:open and !With//Call:open"]}
    profile = build_profile("anything", LLMSettings(enabled=True, model="m"), lambda model: Stub(reply))
    assert profile.source == "llm:m" and [r.text for r in profile.relations] == ["Call:open and !With//Call:open"]


def test_fallback_keeps_the_rules_patterns():
    profile = build_profile("sql injection", LLMSettings(enabled=True), lambda m: Stub(error=LLMError("down")))
    assert profile.source == "rules" and profile.fallback_reason and [r.text for r in profile.relations] == [SQL_BUILT_PATTERN]
    empty = build_profile("sql injection", LLMSettings(enabled=True), lambda m: Stub({"constraints": [], "patterns": []}))
    assert empty.source == "rules" and len(empty.relations) == 1
