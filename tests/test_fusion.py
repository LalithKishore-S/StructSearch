import json
import shutil
from pathlib import Path

import pytest

from structsearch.config import load_config, validate_config
from structsearch.indexing.builder import ensure_index
from structsearch.indexing.dense import ensure_dense_index
from structsearch.indexing.embedder import DenseSettings, HashingEmbedder
from structsearch.interface.cli import main
from structsearch.parsing import extract_all, extract_all_fragments
from structsearch.retrieval.baseline import bm25_search
from structsearch.retrieval.fusion import (
    Signal,
    effective_weights,
    fuse,
    fused_search,
    is_active,
    normalize_scores,
)
from structsearch.retrieval.structural import ConstraintProfile, rules_profile
from structsearch.retrieval.patterns import parse_pattern

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"
IDS = ["a", "b", "c", "d"]
W = {"text": 0.6, "dense": 0.3, "structural": 0.3, "graph": 0.1}


def sig(name, scores, normalize=None, evidence=None):
    return Signal(name, scores, normalize, evidence)


def ranking(outcome):
    return [r.unit_id for r in outcome.results]


# ---- normalization and activity ----

def test_text_is_scaled_by_max_so_the_weakest_match_keeps_its_score():
    s = sig("text", {"a": 4.0, "b": 2.0})
    assert normalize_scores(s, ["a", "b", "c"]) == {"a": 1.0, "b": 0.5, "c": 0.0}  # c has no score: 0
    assert normalize_scores(sig("graph", {"a": 2.0, "b": 1.0}), ["a", "b"]) == {"a": 1.0, "b": 0.5}


def test_dense_is_min_max_over_all_units():
    dense = sig("dense", {"a": -0.2, "b": 0.4, "c": 0.8})
    assert normalize_scores(dense, ["a", "b", "c"]) == pytest.approx({"a": 0.0, "b": 0.6, "c": 1.0})
    assert normalize_scores(sig("dense", {"a": 0.5, "b": 0.5}), ["a", "b"]) == {"a": 0.0, "b": 0.0}


def test_unknown_normalization_is_rejected():
    with pytest.raises(ValueError, match="normalization"):
        normalize_scores(sig("text", {"a": 1.0}, "zscore"), ["a"])


def test_absolute_signals_are_not_stretched_and_are_clamped():
    s = sig("structural", {"a": 0.5, "b": 0.25, "c": 1.7, "d": -1})
    assert normalize_scores(s, IDS) == {"a": 0.5, "b": 0.25, "c": 1.0, "d": 0.0}


def test_activity():
    assert not is_active(sig("text", {}))
    assert not is_active(sig("text", {"a": 0.0, "b": 0.0}))  # no matches
    assert is_active(sig("text", {"a": 3.0, "b": 3.0}))  # every unit matches equally: harmless constant
    assert is_active(sig("text", {"a": 3.0, "b": 0.0}))
    assert not is_active(sig("dense", {"a": 0.4, "b": 0.4}))  # all units equally similar: no information
    assert not is_active(sig("structural", {"a": 0.0}))
    assert is_active(sig("structural", {"a": 0.5, "b": 0.5}))  # absolute: equal scores still count


def test_effective_weights():
    assert effective_weights(["text", "structural"], W) == pytest.approx({"text": 2 / 3, "structural": 1 / 3})
    assert effective_weights(["text"], W) == {"text": 1.0}
    assert effective_weights(["text", "graph"], {"text": 0, "graph": 0}) == {"text": 0.5, "graph": 0.5}
    assert effective_weights(["text", "dense"], {"text": -5, "dense": 1}) == {"text": 0.0, "dense": 1.0}
    assert effective_weights([], W) == {}


# ---- fusion arithmetic ----

def test_weighted_sum_and_order():
    text = sig("text", {"a": 10.0, "b": 6.0, "c": 0.0, "d": 0.0})
    structural = sig("structural", {"a": 0.0, "b": 1.0, "c": 0.5, "d": 0.0})
    out = fuse([text, structural], W, IDS)
    assert out.active == ["text", "structural"] and out.weights == pytest.approx({"text": 2 / 3, "structural": 1 / 3})
    by_id = {r.unit_id: r for r in out.results}
    assert by_id["a"].final_score == pytest.approx(2 / 3)
    assert by_id["b"].final_score == pytest.approx(2 / 3 * 0.6 + 1 / 3)
    assert by_id["c"].final_score == pytest.approx(1 / 3 * 0.5)
    assert "d" not in by_id  # zero everywhere: not a result
    assert ranking(out) == ["b", "a", "c"]
    assert by_id["b"].text_score == pytest.approx(0.6) and by_id["b"].structural_score == 1.0
    assert by_id["b"].dense_score is None and by_id["b"].graph_score is None


def test_missing_signal_renormalizes_instead_of_penalizing():
    text = sig("text", {"a": 4.0, "b": 2.0, "c": 0.0, "d": 0.0})
    base = fuse([text], W, IDS)
    assert base.weights == {"text": 1.0} and base.results[0].final_score == 1.0
    # an all-zero structural signal and a missing graph signal change nothing
    dead = sig("structural", {u: 0.0 for u in IDS})
    assert ranking(fuse([text, dead], W, IDS)) == ranking(base)
    assert [r.final_score for r in fuse([text, dead], W, IDS).results] == [r.final_score for r in base.results]
    assert fuse([text, dead], W, IDS).active == ["text"]


def test_removing_a_signal_equals_giving_it_zero_weight():
    text = sig("text", {"a": 4.0, "b": 2.0, "c": 1.0, "d": 0.0})
    graph = sig("graph", {"a": 0.0, "b": 0.0, "c": 5.0, "d": 1.0})
    without = fuse([text], W, IDS)
    zero = fuse([text, graph], {**W, "graph": 0.0}, IDS)
    assert [(r.unit_id, round(r.final_score, 9)) for r in without.results] == [
        (r.unit_id, round(r.final_score, 9)) for r in zero.results if r.final_score > 0 and r.unit_id != "d"]


def test_graph_signal_changes_the_ranking_and_sets_graph_score():
    text = sig("text", {"a": 4.0, "b": 3.9, "c": 0.0, "d": 0.0})
    graph = sig("graph", {"a": 0.0, "b": 1.0, "c": 0.0, "d": 0.0})
    assert ranking(fuse([text], W, IDS))[0] == "a"
    out = fuse([text, graph], W, IDS)
    assert ranking(out)[0] == "b" and out.results[0].graph_score == 1.0 and out.active == ["text", "graph"]


def test_dense_signal_fields():
    dense = sig("dense", {"a": 0.9, "b": 0.5, "c": 0.1, "d": 0.1})
    out = fuse([dense], W, IDS)
    assert out.results[0].unit_id == "a" and out.results[0].dense_score == 1.0 and out.results[0].text_score == 0.0
    assert "d" not in ranking(out) and "c" not in ranking(out)  # lowest score normalizes to 0


def test_nothing_active_and_unknown_signal():
    assert fuse([], W, IDS).results == [] and fuse([sig("text", {"a": 0.0})], W, IDS).active == []
    with pytest.raises(ValueError, match="unknown signal"):
        fuse([sig("bogus", {"a": 1.0, "b": 0.0})], W, IDS)


def test_k_ties_and_determinism():
    text = sig("text", {"a": 1.0, "b": 1.0, "c": 1.0, "d": 0.0})
    out = fuse([text], W, IDS, k=2)
    assert ranking(out) == ["a", "b"]  # equal scores: unit_id order
    assert fuse([text], W, IDS, k=0).results == []
    assert ranking(fuse([text], W, IDS)) == ranking(fuse([text], W, IDS))


def test_evidence_breakdown_and_lazy_callbacks():
    calls = []

    def text_ev(uid):
        calls.append(uid)
        return [f"term match for {uid}"]

    text = sig("text", {"a": 4.0, "b": 2.0, "c": 1.0, "d": 0.0}, evidence=text_ev)
    out = fuse([text], W, IDS, k=2, extra_evidence=lambda uid: "note" if uid == "a" else None)
    assert out.results[0].evidence[0].startswith("fusion: text 1.00x1.00 = 1.000")
    assert out.results[0].evidence[1:] == ["term match for a", "note"]
    assert out.results[1].evidence[-1] == "term match for b"
    assert calls == ["a", "b"]  # evidence is only computed for returned results


# ---- fused_search over real indexes ----

MISLEADING = '''def walk_nodes(node):
    """Depth first walk."""
    if node is None:
        return
    walk_nodes(node.left)
    walk_nodes(node.right)


def walk_with_stack(node):
    """Walk the tree, recursive style but written with a loop (recursive recursive)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current:
            stack.append(current.left)
            stack.append(current.right)
'''


@pytest.fixture()
def misleading_corpus(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    (root / "walk.py").write_text(MISLEADING)
    return root


def build(corpus, tmp_path):
    units, index, _ = ensure_index(corpus, tmp_path / "idx")
    return {u.unit_id: u for u in units}, units, index


def test_structure_corrects_a_misleading_docstring(misleading_corpus, tmp_path):
    units_by_id, units, index = build(misleading_corpus, tmp_path)
    query = "recursive tree walk"
    text_only = bm25_search(index, units_by_id, query, k=2)
    assert text_only[0].unit_id == "walk.py::walk_with_stack"  # the docstring says 'recursive' twice
    out = fused_search(query, units_by_id, index, {"text": 0.6, "structural": 0.3, "graph": 0.1}, k=2,
                       profile=rules_profile(query), ast_records=extract_all(units))
    assert ranking(out) == ["walk.py::walk_nodes", "walk.py::walk_with_stack"]
    assert out.active == ["text", "structural"]


def test_query_without_structure_equals_plain_bm25(tmp_path):
    units_by_id, units, index = build(CORPUS, tmp_path)
    query = "read file lines"
    plain = bm25_search(index, units_by_id, query, k=5)
    out = fused_search(query, units_by_id, index, W, k=5, profile=rules_profile(query), ast_records=extract_all(units))
    assert out.active == ["text"] and ranking(out) == [r.unit_id for r in plain]
    assert out.results[0].final_score == 1.0


def test_patterns_participate_through_fragments(tmp_path):
    units_by_id, units, index = build(CORPUS, tmp_path)
    profile = ConstraintProfile(relations=(parse_pattern("BinOp:Add=>Call:execute"),))
    out = fused_search("find user", units_by_id, index, W, k=3, profile=profile,
                       ast_records=extract_all(units), fragments=extract_all_fragments(units))
    assert out.active == ["text", "structural"] and ranking(out)[0] == "db.py::find_user_unsafe"
    assert any("BinOp:Add before Call:execute" in line for line in out.results[0].evidence)
    # without fragments the pattern cannot be checked, so the structural signal carries nothing
    blind = fused_search("find user", units_by_id, index, W, k=3, profile=profile, ast_records=extract_all(units))
    assert blind.active == ["text"]


def test_failed_file_units_stay_findable_but_get_no_structural_credit(tmp_path):
    units_by_id, units, index = build(CORPUS, tmp_path)
    query = "broken function recursive"
    out = fused_search(query, units_by_id, index, W, k=20, profile=rules_profile(query), ast_records=extract_all(units))
    broken = next(r for r in out.results if r.unit_id == "broken_syntax.py::<module>")
    assert broken.structural_score == 0.0 and broken.text_score > 0
    assert any("file did not parse" in line for line in broken.evidence)


def test_hybrid_adds_dense_and_graph(tmp_path):
    units_by_id, units, index = build(CORPUS, tmp_path)
    settings = DenseSettings(backend="hashing")
    dense_index, _ = ensure_dense_index(units, tmp_path / "idx", HashingEmbedder(), settings)
    kwargs = dict(profile=rules_profile("validate input"), ast_records=extract_all(units),
                  dense=(dense_index, HashingEmbedder(), settings))
    weights = load_config()["hybrid_weights"]
    out = fused_search("validate input", units_by_id, index, weights, k=3, **kwargs)
    assert out.active == ["text", "dense", "structural"] and sum(out.weights.values()) == pytest.approx(1.0)
    assert out.results[0].unit_id == "db.py::validate_user_input" and out.results[0].dense_score is not None
    with_graph = fused_search("validate input", units_by_id, index, weights, k=3,
                              graph_scores={"db.py::get_user": 1.0, "db.py::count_rows": 0.0}, **kwargs)
    assert with_graph.active == ["text", "dense", "structural", "graph"]
    assert all(r.graph_score is not None for r in with_graph.results)


# ---- config ----

def test_default_config_has_valid_hybrid_weights():
    cfg = load_config()
    assert set(cfg["hybrid_weights"]) == {"text", "dense", "structural", "graph"}


@pytest.mark.parametrize("bad", [
    {"text": 1, "structural": 1, "graph": 1},  # no dense
    {"text": 1, "dense": -1, "structural": 1, "graph": 1},
    {"text": 0, "dense": 0, "structural": 0, "graph": 0},
])
def test_hybrid_weight_validation(bad):
    cfg = load_config()
    cfg["hybrid_weights"] = bad
    with pytest.raises(ValueError):
        validate_config(cfg)


# ---- CLI ----

@pytest.fixture()
def cli_corpus(tmp_path):
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


def search(capsys, tmp_path, corpus, *args):
    code = main(["search", *args, "--corpus", str(corpus), "--index-dir", str(tmp_path / "idx"), "--embedder", "hashing"])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_text_ast_mode(capsys, tmp_path, cli_corpus):
    code, out, err = search(capsys, tmp_path, cli_corpus, "recursive tree traversal", "--mode", "text_ast", "-k", "3", "--lines", "0")
    assert code == 0 and "mode: text_ast" in out
    assert out.index("trees.py::inorder_traverse") < out.index("trees.py::factorial")
    w = load_config()["weights"]  # configured weights, renormalized over the two signals that took part
    text_w, structural_w = (w[n] / (w["text"] + w["structural"]) for n in ("text", "structural"))
    assert f"fusion: text 1.00x{text_w:.2f} + structural 1.00x{structural_w:.2f} = 1.000" in out
    assert f"fusion signals: text {text_w:.2f}, structural {structural_w:.2f}" in err


def test_text_ast_json(capsys, tmp_path, cli_corpus):
    code, out, _ = search(capsys, tmp_path, cli_corpus, "recursive tree traversal", "--mode", "text_ast", "--json", "-k", "2", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and payload["fusion"]["signals"] == ["text", "structural"]
    assert sum(payload["fusion"]["weights"].values()) == pytest.approx(1.0)
    assert payload["profile"]["constraints"][0]["features"] == ["self_call"]
    top = payload["results"][0]
    assert top["unit_id"] == "trees.py::inorder_traverse" and top["final_score"] == 1.0 and top["dense_score"] is None


def test_query_without_structural_words_says_so(capsys, tmp_path, cli_corpus):
    code, out, err = search(capsys, tmp_path, cli_corpus, "read file lines", "--mode", "text_ast", "--lines", "0")
    assert code == 0 and "ranking without the structure signal" in err and "fusion signals: text 1.00" in err
    assert "files.py::read_lines" in out


def test_hybrid_mode(capsys, tmp_path, cli_corpus):
    code, out, err = search(capsys, tmp_path, cli_corpus, "validate user input", "--mode", "hybrid", "--json", "-k", "3", "--lines", "0")
    payload = json.loads(out)
    assert code == 0 and payload["fusion"]["signals"] == ["text", "dense", "structural", "graph"]  # "validate" names a graph relationship
    assert payload["embedding_model"].startswith("hashing") and payload["results"][0]["dense_score"] is not None
    assert "dense index built" in err


def test_weight_override_changes_weights_and_can_remove_a_signal(capsys, tmp_path, cli_corpus):
    code, out, _ = search(capsys, tmp_path, cli_corpus, "recursive tree traversal", "--mode", "text_ast", "--json",
                          "--weight", "structural=0", "--weight", "text=1", "--lines", "0")
    payload = json.loads(out)
    assert payload["fusion"]["weights"] == {"text": 1.0} and payload["fusion"]["signals"] == ["text"]  # structure removed
    code, out, _ = search(capsys, tmp_path, cli_corpus, "recursive tree traversal", "--mode", "text_ast", "--json",
                          "--weight", "structural=3", "--lines", "0")
    assert json.loads(out)["fusion"]["weights"]["structural"] == pytest.approx(3 / (load_config()["weights"]["text"] + 3), abs=1e-4)


@pytest.mark.parametrize("bad", ["structural", "bogus=1", "text=abc", "text=-1", "text=nan", "text=inf"])
def test_bad_weight_is_a_clean_error(capsys, tmp_path, cli_corpus, bad):
    code, out, err = search(capsys, tmp_path, cli_corpus, "recursive", "--mode", "text_ast", "--weight", bad)
    assert code == 2 and "--weight" in err and out == ""


def test_bad_pattern_in_fused_mode(capsys, tmp_path, cli_corpus):
    code, _, err = search(capsys, tmp_path, cli_corpus, "x", "--mode", "text_ast", "--pattern", "Foo//Try")
    assert code == 2 and "bad --pattern" in err


def test_explicit_pattern_flag_in_text_ast(capsys, tmp_path, cli_corpus):
    code, out, _ = search(capsys, tmp_path, cli_corpus, "find user", "--mode", "text_ast", "--pattern", "BinOp:Add=>Call:execute",
                          "--json", "--lines", "0", "-k", "1")
    assert code == 0 and json.loads(out)["results"][0]["unit_id"] == "db.py::find_user_unsafe"


def test_existing_modes_unchanged(capsys, tmp_path, cli_corpus):
    for mode in ("bm25", "dense", "structural"):
        code, out, _ = search(capsys, tmp_path, cli_corpus, "recursive", "--mode", mode, "-k", "1", "--lines", "0")
        assert code == 0 and f"mode: {mode}" in out


# ---- a zero weight removes the signal ----

def test_zero_weight_signal_is_removed_even_when_the_others_have_no_evidence():
    text = sig("text", {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0})  # BM25 matched nothing
    structural = sig("structural", {"a": 1.0, "b": 0.5, "c": 0.0, "d": 0.0}, "none")
    outcome = fuse([text, structural], {"text": 1.0, "structural": 0.0}, IDS)
    assert outcome.results == [] and outcome.active == []  # structure was removed, not promoted to full weight


def test_zero_weight_signal_is_dropped_from_the_active_signals():
    text = sig("text", {"a": 1.0, "b": 0.5, "c": 0.0, "d": 0.0})
    structural = sig("structural", {"a": 0.0, "b": 1.0, "c": 0.0, "d": 0.0}, "none")
    outcome = fuse([text, structural], {"text": 1.0, "structural": 0.0}, IDS)
    assert outcome.active == ["text"] and outcome.weights == {"text": 1.0}
    assert ranking(outcome) == ["a", "b"]


def test_all_zero_weights_still_fall_back_to_equal_weights():
    text = sig("text", {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0})
    structural = sig("structural", {"a": 0.0, "b": 1.0, "c": 0.0, "d": 0.0}, "none")
    outcome = fuse([text, structural], {"text": 0.0, "structural": 0.0}, IDS)
    assert outcome.active == ["text", "structural"] and outcome.weights == {"text": 0.5, "structural": 0.5}
