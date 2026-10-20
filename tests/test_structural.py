import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from structsearch.config import load_config, validate_config
from structsearch.ingestion import ingest_corpus
from structsearch.llm import LLMError, LLMSettings, ModelMissingError, OllamaJSON
from structsearch.parsing import extract_all
from structsearch.retrieval.structural import (
    Constraint,
    ConstraintProfile,
    build_profile,
    constraint_score,
    llm_schema,
    match_unit,
    parse_llm_constraints,
    rules_profile,
    structural_scores,
    structural_search,
)

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


@pytest.fixture(scope="module")
def corpus():
    result = ingest_corpus(CORPUS)
    return {u.unit_id: u for u in result.units}, extract_all(result.units)


def keys(profile):
    return {(c.features, c.op) for c in profile.constraints}


# ---- rule-based mapper ----

@pytest.mark.parametrize(
    "query, expected",
    [
        ("recursive tree traversal", {(("self_call",), "present")}),
        ("function that calls itself", {(("self_call",), "present")}),
        ("read a file without error handling", {(("try_count",), "absent")}),
        ("file access with exception handling", {(("try_with_handler_count",), "present")}),
        ("catches errors when parsing", {(("try_with_handler_count",), "present")}),
        ("raises an exception on bad input", {(("raise_count",), "present")}),
        ("validate user input", {(("guard_clause_count", "raise_in_if_count", "type_check_count"), "present")}),
        ("missing input validation", {(("guard_clause_count", "raise_in_if_count", "type_check_count"), "absent")}),
        ("unvalidated user input", {(("guard_clause_count", "raise_in_if_count", "type_check_count"), "absent")}),
        ("uncaught exceptions", {(("try_count",), "absent")}),
        ("async function that awaits", {(("is_async",), "present")}),
        ("generator that yields items", {(("is_generator",), "present")}),
        ("uses a while loop", {(("while_count",), "present")}),
        ("iterates with a for loop", {(("for_count",), "present")}),
        ("iterate over items", {(("for_count", "while_count"), "present")}),
        ("nested loops", {(("max_loop_depth",), "at_least")}),
        ("deeply nested conditionals", {(("max_depth",), "at_least")}),
        ("swallows exceptions silently", {(("bare_except_count",), "present")}),
        ("closes the file with a context manager", {(("with_count",), "present")}),
        ("without closing the file", {(("with_count",), "absent")}),
        ("parse a csv", set()),
        ("", set()),
    ],
)
def test_rules_known_queries(query, expected):
    assert keys(rules_profile(query)) == expected


def test_negation_is_scoped_to_its_phrase():
    # "not recursive" must not flip the loop wish that follows "but"
    got = keys(rules_profile("not recursive but uses loops"))
    assert got == {(("self_call",), "absent"), (("for_count", "while_count"), "present")}
    # a negator three words back no longer applies
    assert keys(rules_profile("without any of the usual fuss recursive")) == {(("self_call",), "present")}
    # words in between are allowed
    assert keys(rules_profile("without proper error handling")) == {(("try_count",), "absent")}
    assert keys(rules_profile("doesn't validate input")) == {
        (("guard_clause_count", "raise_in_if_count", "type_check_count"), "absent")
    }


def test_specific_phrases_consume_generic_ones():
    assert len(rules_profile("while loop").constraints) == 1
    nested = rules_profile("nested loops")
    assert len(nested.constraints) == 1 and nested.constraints[0].value == 2


def test_rules_are_case_insensitive_deduplicated_and_capped():
    assert rules_profile("RECURSIVE recursion recursively").constraints == rules_profile("recursive").constraints
    assert len(rules_profile("recursive loop async generator assert decorator lambda comprehension "
                             "conditional validate raise finally nested function bare except").constraints) <= 8


def test_rules_profile_describes_itself():
    profile = rules_profile("recursive without error handling")
    assert profile.source == "rules" and profile.fallback_reason is None
    assert "recursion" in profile.describe() and "no error handling" in profile.describe()
    assert ConstraintProfile().describe().startswith("no structural")
    assert profile.to_dict()["constraints"][0]["features"] == ["self_call"]


# ---- scoring ----

def test_constraint_scores():
    present = Constraint(("a",), "present")
    assert [constraint_score(present, v) for v in (0, 1, 3)] == [0.0, 1.0, 1.0]
    assert [constraint_score(Constraint(("a",), "absent"), v) for v in (0, 1)] == [1.0, 0.0]
    at_least = Constraint(("a",), "at_least", 4)
    assert [constraint_score(at_least, v) for v in (0, 2, 4, 9)] == [0.0, 0.5, 1.0, 1.0]
    at_most = Constraint(("a",), "at_most", 2)
    assert [constraint_score(at_most, v) for v in (0, 2, 4)] == [1.0, 1.0, 0.5]
    assert constraint_score(Constraint(("a",), "at_most", 0), 1) == 0.0
    with pytest.raises(ValueError):
        constraint_score(Constraint(("a",), "bogus"), 1)


def test_match_unit_weighted_average_and_empty_profile():
    profile = ConstraintProfile((
        Constraint(("self_call",), "present", weight=1.0, reason="recursion"),
        Constraint(("try_count",), "absent", weight=0.5, reason="no handling"),
    ))
    both = match_unit(profile, {"self_call": 1.0, "try_count": 0.0})
    assert both.score == 1.0 and len(both.matched) == 2 and not both.missed
    half = match_unit(profile, {"self_call": 1.0, "try_count": 2.0})
    assert half.score == pytest.approx(1.0 / 1.5) and len(half.missed) == 1
    assert match_unit(profile, {}).score == pytest.approx(0.5 / 1.5)  # missing feature counts as 0
    assert match_unit(ConstraintProfile(), {"self_call": 1.0}).score == 0.0


def test_aggregate_features_act_as_any_of():
    c = Constraint(("for_count", "while_count"), "present")
    p = ConstraintProfile((c,))
    assert match_unit(p, {"for_count": 0, "while_count": 1}).score == 1.0
    assert match_unit(p, {"for_count": 0, "while_count": 0}).score == 0.0


# ---- retrieval over the fixture corpus ----

def test_recursive_query_boosts_recursive_functions(corpus):
    units, records = corpus
    results = structural_search(rules_profile("recursive traversal"), units, records, k=10)
    ids = [r.unit_id for r in results]
    assert set(ids) == {"trees.py::inorder_traverse", "trees.py::factorial"}
    assert "trees.py::count_nodes" not in ids  # iterative traversal
    assert all(r.structural_score == 1.0 == r.final_score and r.text_score == 0.0 for r in results)
    assert any("recursion (self_call=1)" in line for line in results[0].evidence)


def test_absent_constraint_excludes_functions_with_try(corpus):
    units, records = corpus
    ids = [r.unit_id for r in structural_search(rules_profile("without error handling"), units, records, k=50)]
    assert "files.py::read_config_safe" not in ids and "files.py::read_lines" in ids


def test_failed_file_units_never_match_structurally(corpus):
    units, records = corpus
    for query in ("without error handling", "no validation", "recursive"):
        ids = [r.unit_id for r in structural_search(rules_profile(query), units, records, k=50)]
        assert "broken_syntax.py::<module>" not in ids
    scores = structural_scores(rules_profile("without error handling"), records)
    assert scores["broken_syntax.py::<module>"] == 0.0 and set(scores) == set(units)


def test_partial_matches_rank_by_score_then_id_and_show_misses(corpus):
    units, records = corpus
    profile = rules_profile("recursive loop")
    results = structural_search(profile, units, records, k=50)
    scores = [r.final_score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert 0.0 < scores[-1] < 1.0 or len(set(scores)) == 1
    top_fractional = next((r for r in results if r.final_score < 1.0), None)
    if top_fractional:
        assert any(line.startswith("structural miss:") for line in top_fractional.evidence)
    again = structural_search(profile, units, records, k=50)
    assert [r.unit_id for r in results] == [r.unit_id for r in again]


def test_k_limit_empty_profile_and_unknown_records(corpus):
    units, records = corpus
    assert len(structural_search(rules_profile("without error handling"), units, records, k=2)) == 2
    assert structural_search(ConstraintProfile(), units, records, k=5) == []
    assert structural_search(rules_profile("recursive"), {}, records, k=5) == []
    assert structural_search(rules_profile("recursive"), units, records, k=0) == []


# ---- validating model output ----

def test_parse_llm_constraints_accepts_valid_output():
    out = parse_llm_constraints({"constraints": [
        {"features": ["self_call"], "op": "present", "reason": "recursion"},
        {"feature": "max_depth", "op": "at_least", "value": 3, "weight": 0.5},
    ]})
    assert out[0] == Constraint(("self_call",), "present", 1.0, 1.0, "recursion")
    assert out[1] == Constraint(("max_depth",), "at_least", 3.0, 0.5, "")
    assert parse_llm_constraints([{"features": ["if_count"], "op": "absent"}])[0].op == "absent"  # bare list
    assert parse_llm_constraints({"constraints": []}) == []  # "no structural wish" is a valid answer


def test_parse_llm_constraints_drops_bad_items_and_rejects_all_bad():
    mixed = parse_llm_constraints({"constraints": [
        {"features": ["not_a_feature"], "op": "present"},
        {"features": ["self_call"], "op": "sometimes"},
        "junk",
        {"features": [], "op": "present"},
        {"features": ["self_call"], "op": "present"},
    ]})
    assert [c.features for c in mixed] == [("self_call",)]
    for bad in (
        {"constraints": [{"features": ["nope"], "op": "present"}]},
        {"constraints": "present"},
        "text",
        None,
        {"other": []},
    ):
        with pytest.raises(ValueError):
            parse_llm_constraints(bad)


def test_parse_llm_constraints_clamps_numbers():
    c = parse_llm_constraints({"constraints": [
        {"features": ["max_depth"], "op": "at_least", "value": 1e9, "weight": 7},
        {"features": ["call_count"], "op": "at_least", "value": -3, "weight": float("nan")},
        {"features": ["if_count"], "op": "at_most", "value": "many", "weight": True},
    ]})
    assert c[0].value == 1000.0 and c[0].weight == 1.0
    assert c[1].value == 1.0 and c[1].weight == 1.0  # non-positive threshold and NaN weight replaced
    assert c[2].value == 1.0 and c[2].weight == 1.0


def test_parse_llm_constraints_dedupes_and_caps():
    items = [{"features": ["self_call"], "op": "present"}] * 3
    assert len(parse_llm_constraints({"constraints": items})) == 1
    many = [{"features": [name], "op": "present"} for name in ("if_count", "for_count", "while_count", "try_count",
            "with_count", "raise_count", "return_count", "assert_count", "yield_count", "await_count")]
    assert len(parse_llm_constraints({"constraints": many})) == 8


def test_schema_lists_exactly_the_known_features():
    from structsearch.parsing import FEATURE_NAMES

    schema = llm_schema()
    enum = schema["properties"]["constraints"]["items"]["properties"]["features"]["items"]["enum"]
    assert enum == list(FEATURE_NAMES)


# ---- build_profile with stub clients ----

class Stub:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def generate_json(self, prompt, schema=None):
        if self.error:
            raise self.error
        return self.reply


def enabled(**kw):
    return LLMSettings(enabled=True, **kw)


def test_build_profile_without_llm_is_rules_only():
    assert build_profile("recursive").source == "rules"
    assert build_profile("recursive", LLMSettings(enabled=False), lambda m: pytest.fail("must not be called")).source == "rules"


def test_build_profile_uses_valid_llm_answer():
    reply = {"constraints": [{"features": ["self_call"], "op": "present", "reason": "recursion"}]}
    profile = build_profile("anything", enabled(model="m1"), lambda model: Stub(reply))
    assert profile.source == "llm:m1" and profile.fallback_reason is None
    assert profile.constraints[0].features == ("self_call",)


@pytest.mark.parametrize(
    "stub",
    [
        Stub(error=LLMError("down")),
        Stub(reply={"constraints": [{"features": ["bogus"], "op": "present"}]}),
        Stub(reply="not an object"),
        Stub(reply={"constraints": []}),
    ],
)
def test_build_profile_falls_back_to_rules(stub):
    profile = build_profile("recursive tree traversal", enabled(), lambda model: stub)
    assert profile.source == "rules" and profile.fallback_reason
    assert keys(profile) == {(("self_call",), "present")}


def test_missing_primary_model_tries_fallback_model():
    seen = []

    def factory(model):
        seen.append(model)
        if model == "big":
            return Stub(error=ModelMissingError("pull big"))
        return Stub({"constraints": [{"features": ["try_count"], "op": "absent"}]})

    profile = build_profile("q", enabled(model="big", fallback_model="small"), factory)
    assert seen == ["big", "small"] and profile.source == "llm:small"


def test_all_models_missing_falls_back():
    profile = build_profile("recursive", enabled(model="a", fallback_model="b"),
                            lambda m: Stub(error=ModelMissingError("pull " + m)))
    assert profile.source == "rules" and "pull b" in profile.fallback_reason


# ---- the Ollama JSON client against a fake server ----

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        server = self.server
        server.requests.append((self.path, body))
        if self.path != "/api/generate":
            return self._send(404, b"404 page not found")
        if server.mode == "missing_model":
            return self._send(404, {"error": 'model "x" not found, try pulling it first'})
        if server.mode == "schema_400" and isinstance(body["format"], dict):
            return self._send(400, {"error": "invalid format"})
        if server.mode == "server_error":
            return self._send(500, {"error": "boom"})
        if server.mode == "empty":
            return self._send(200, {"response": ""})
        if server.mode == "not_json":
            return self._send(200, {"response": "Sure! Here you go"})
        if server.mode == "garbage_body":
            return self._send(200, b"<html>")
        self._send(200, {"response": json.dumps(server.answer)})


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.mode, srv.requests = "ok", []
    srv.answer = {"constraints": [{"features": ["self_call"], "op": "present", "reason": "recursion"}]}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def host(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_client_sends_schema_and_zero_temperature(server):
    data = OllamaJSON("m", host(server), timeout=5).generate_json("prompt", llm_schema())
    assert data == server.answer
    path, body = server.requests[0]
    assert path == "/api/generate" and body["model"] == "m" and body["stream"] is False
    assert body["format"] == llm_schema() and body["options"] == {"temperature": 0}


def test_client_retries_plain_json_when_schema_rejected(server):
    server.mode = "schema_400"
    assert OllamaJSON("m", host(server), timeout=5).generate_json("p", llm_schema()) == server.answer
    assert [r[1]["format"] == "json" for r in server.requests] == [False, True]


@pytest.mark.parametrize("mode, text", [
    ("missing_model", "ollama pull"),
    ("server_error", "HTTP 500"),
    ("empty", "empty response"),
    ("not_json", "valid JSON"),
    ("garbage_body", "not valid JSON"),
])
def test_client_errors_are_readable(server, mode, text):
    server.mode = mode
    with pytest.raises(LLMError, match=text):
        OllamaJSON("m", host(server), timeout=5).generate_json("p")


def test_client_missing_model_is_its_own_error_type(server):
    server.mode = "missing_model"
    with pytest.raises(ModelMissingError):
        OllamaJSON("m", host(server), timeout=5).generate_json("p")


def test_client_unreachable_server():
    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        OllamaJSON("m", "http://127.0.0.1:9", timeout=2).generate_json("p")


def test_build_profile_end_to_end_with_fake_server(server):
    settings = enabled(host=host(server), model="qwen", fallback_model="", timeout_seconds=5)
    profile = build_profile("whatever the user typed", settings)
    assert profile.source == "llm:qwen" and profile.constraints[0].features == ("self_call",)
    server.mode = "not_json"
    fallback = build_profile("recursive", settings)
    assert fallback.source == "rules" and "valid JSON" in fallback.fallback_reason


# ---- config ----

def test_llm_settings_from_config_and_overrides():
    s = LLMSettings.from_config(load_config(), model="other", enabled=True)
    assert s.model == "other" and s.enabled and s.fallback_model == "qwen2.5-coder:3b"
    assert LLMSettings.from_config(load_config()).enabled is False
    assert LLMSettings.from_config(None).model == "qwen2.5-coder:7b"


@pytest.mark.parametrize("bad", [
    {"backend": "openai"}, {"enabled": "yes"}, {"model": " "}, {"timeout_seconds": 0},
])
def test_llm_config_validation(bad):
    cfg = load_config()
    cfg["llm"] = {**cfg["llm"], **bad}
    with pytest.raises(ValueError):
        validate_config(cfg)
