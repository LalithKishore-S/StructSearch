import json
import shutil
from pathlib import Path

import pytest

from structsearch.interface.results_data import (
    VARIANT_LABELS,
    VARIANT_ORDER,
    ablation_rows,
    error_analysis,
    load_results,
    metric_rows,
    paired_rows,
    query_detail,
    query_outcomes,
    split_note,
)

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def run():
    data = load_results()
    assert data is not None
    return data


def by_label(rows):
    return {r["variant"]: r for r in rows}


# ------------------------------------------------------------------ loading


def test_load_results_reads_the_committed_final_run(run):
    assert run.info["splits"] == ["dev", "test"] and run.info["ks"] == [1, 3, 5] and run.info["baseline"] == "bm25"
    assert len(run.queries) == 34 and len(run.labels) == 34
    assert {r["split"] for r in run.per_query} == {"dev", "test"}
    assert set(VARIANT_ORDER) == {r["variant"] for r in run.summary}
    assert all(v in VARIANT_LABELS for v in VARIANT_ORDER)


def test_the_run_was_made_on_the_frozen_benchmark(run):
    assert run.benchmark_matches_lock is True


def test_missing_run_gives_none(tmp_path):
    assert load_results(tmp_path / "nothing") is None


def test_changed_benchmark_is_detected(tmp_path):
    runs = tmp_path / "final"
    shutil.copytree(ROOT / "experiments" / "runs" / "final", runs)
    info = json.loads((runs / "run.json").read_text())
    info["benchmark_lock"]["labels_sha256"] = "0" * 64
    (runs / "run.json").write_text(json.dumps(info))
    assert load_results(runs).benchmark_matches_lock is False


# ------------------------------------------------------------------ tables


def test_test_split_metrics_match_the_documented_results(run):
    allq = by_label(metric_rows(run, "test", "all", 3))
    assert allq["bm25"]["nDCG@k"] == pytest.approx(0.787, abs=1e-3)
    assert allq["text_ast_graph"]["nDCG@k"] == pytest.approx(0.952, abs=1e-3)
    rel = by_label(metric_rows(run, "test", "relationship", 3))
    assert rel["bm25"]["nDCG@k"] == pytest.approx(0.673, abs=1e-3)
    assert rel["text_ast_graph"]["nDCG@k"] == pytest.approx(0.962, abs=1e-3)
    assert [r["variant"] for r in metric_rows(run, "test", "all", 3)] == list(VARIANT_ORDER)
    assert all(r["n"] == 14 for r in metric_rows(run, "test", "all", 3))


def test_ablation_rows(run):
    rows = ablation_rows(run, "test", "relationship", 3)
    got = {r["variant"]: r for r in rows}
    assert [r["label"] for r in rows][0] == VARIANT_LABELS["text_ast_graph"]
    assert got["text_ast_graph"]["delta"] == 0
    assert got["text_ast_graph-graph"]["value"] == pytest.approx(0.750, abs=1e-3)
    assert got["text_ast_graph-structural"]["value"] == pytest.approx(0.913, abs=1e-3)
    assert got["text_ast_graph-text"]["value"] == pytest.approx(0.869, abs=1e-3)
    assert got["text_ast_graph-graph"]["delta"] == pytest.approx(0.750 - 0.962, abs=2e-3)
    assert set(got) == {"text_ast_graph", "text_ast_graph-text", "text_ast_graph-structural", "text_ast_graph-graph"}


def test_paired_rows(run):
    rows = {r["variant"]: r for r in paired_rows(run, "test", "relationship", 3)}
    full = rows["text_ast_graph"]
    assert (full["wins"], full["ties"], full["losses"]) == (4, 4, 0) and full["n"] == 8
    assert full["label"] == VARIANT_LABELS["text_ast_graph"] and "bm25" not in rows
    assert rows["text_ast"]["losses"] == 0


# ------------------------------------------------------------------ per query


def test_query_outcomes_count_wins_ties_and_losses(run):
    outcomes = query_outcomes(run, "test", "text_ast_graph", "bm25", 3)
    assert len(outcomes) == 14
    tally = {k: sum(o["outcome"] == k for o in outcomes) for k in ("win", "tie", "loss")}
    assert tally == {"win": 4, "tie": 10, "loss": 0}
    wins = {o["query_id"] for o in outcomes if o["outcome"] == "win"}
    assert {"R14", "R17"} <= wins
    assert all(o["delta"] >= 0 for o in outcomes)


def test_query_outcome_fields(run):
    r17 = next(o for o in query_outcomes(run, "test", "text_ast_graph", "bm25", 5) if o["query_id"] == "R17")
    assert r17["baseline_rank"] is None and r17["variant_rank"] == 2 and r17["outcome"] == "win"
    assert r17["query"] == "opening files without catching exceptions" and r17["category"] == "relationship"


def test_query_detail_marks_relevant_results(run):
    detail = query_detail(run, "R17", 5)
    assert detail["relevant"] == ["files.py::read_lines", "files.py::write_log"]
    bm25 = next(v for v in detail["variants"] if v["variant"] == "bm25")
    full = next(v for v in detail["variants"] if v["variant"] == "text_ast_graph")
    assert not any(item["relevant"] for item in bm25["ranking"]) and bm25["first_relevant"] is None
    assert full["first_relevant"] == 2 and full["ranking"][1]["relevant"] is True
    assert [v["variant"] for v in detail["variants"]] == list(VARIANT_ORDER)
    assert detail["split"] == "test" and detail["category"] == "relationship"
    with pytest.raises(KeyError):
        query_detail(run, "nope", 3)


def test_ranking_is_cut_at_k(run):
    detail = query_detail(run, "R17", 1)
    assert all(len(v["ranking"]) <= 1 for v in detail["variants"])


def test_error_analysis_groups(run):
    groups = error_analysis(query_outcomes(run, "test", "text_ast_graph", "bm25", 3))
    assert {o["query_id"] for o in groups["improved"]} >= {"R14", "R17"} and not groups["regressed"]
    unsolved = {o["query_id"] for o in groups["unsolved"]}
    assert "L12" in unsolved
    assert len(groups["improved"]) + len(groups["solved"]) + len(groups["unsolved"]) + len(groups["regressed"]) == 14


def test_dev_analysis_includes_the_known_failure(run):
    groups = error_analysis(query_outcomes(run, "dev", "text_ast_graph", "bm25", 3))
    assert "R12" in {o["query_id"] for o in groups["unsolved"]}
    assert "R08" in {o["query_id"] for o in groups["improved"]}


def test_split_note_warns_about_the_tuning_set():
    assert "tuned" in split_note("dev") and "once" in split_note("test")
