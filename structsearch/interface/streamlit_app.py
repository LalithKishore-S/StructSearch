"""Streamlit front end:  streamlit run structsearch/interface/streamlit_app.py

Four tabs: Search (how the query was understood, score breakdown per signal, the evidence graph the ranking used,
code and evidence), Security candidates (SQL-construction candidates for review), Call graph (the whole graph) and
Results (the experiment: variants, ablations, per-query errors, read from experiments/runs/).
It ranks with the full model (BM25 + AST structure + call graph) and works offline; the other modes, custom weights
and `llm` explanations are available from the command line.

The data behind each panel is prepared by structsearch.interface.ui_data (unit-tested without Streamlit).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# `streamlit run` puts this file's folder on sys.path, not the repo root.
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from structsearch.config import load_config
from structsearch.graph import CodeGraph, ensure_graph
from structsearch.interface import results_data as rd
from structsearch.interface.explain import explain_results
from structsearch.interface.format import result_to_dict
from structsearch.interface.service import SearchError, SearchRequest, SearchResponse, load_corpus, run_search
from structsearch.interface.ui_data import (
    DEMO_QUERIES,
    LEGEND,
    SIGNAL_LABELS,
    SIGNAL_ORDER,
    breakdown_long,
    candidate_rows,
    evidence_graph_dot,
    full_graph_dot,
    score_breakdown,
    understand_query,
    unit_card,
)
from structsearch.llm.ollama import LLMSettings
from structsearch.security import DISCLAIMER, NOT_MODELLED, PATTERN_QUERY, scan_sql_candidates

MODE = "text_ast_graph"  # the full model: BM25 + AST structure + call graph (the other modes stay in the CLI)


# --------------------------------------------------------------------------- data (no Streamlit)


def search_rows(query: str, mode: str, k: int, corpus: str, index_dir: str, explain: str, use_llm_mapper: bool,
                patterns: List[str]) -> Dict[str, Any]:
    """Run one search and return plain data for display (no Streamlit needed; unit-testable)."""
    cfg = load_config()
    settings = LLMSettings.from_config(cfg, enabled=True if use_llm_mapper else None)
    response = run_search(
        SearchRequest(query=query, mode=mode, k=k, corpus=corpus, index_dir=index_dir,
                      llm=settings, patterns=patterns),
        cfg,
    )
    notes: List[str] = []
    explanations = None
    if explain != "none":
        explanations = explain_results(query, response.results, response.units_by_id, method=explain,
                                       llm=LLMSettings.from_config(cfg, enabled=True), notify=notes.append)
    rows = [
        result_to_dict(r, response.units_by_id[r.unit_id], 12, (explanations or {}).get(r.unit_id))
        for r in response.results
    ]
    return {"rows": rows, "total_units": response.total_units, "extra": response.extra, "notes": notes}


@dataclass
class UISearch:
    """Everything the Search tab shows for one query."""

    response: SearchResponse
    understanding: Dict[str, Any]
    breakdown: List[Dict[str, Any]]
    rows: List[Dict[str, Any]]
    graph: CodeGraph
    notes: List[str] = field(default_factory=list)


def run_ui_search(query: str, mode: str, k: int, corpus: str, index_dir: str, explain: str = "template",
                  use_llm_mapper: bool = False, patterns: Sequence[str] = (), intents: Sequence[str] = (),
                  weights: Sequence[str] = ()) -> UISearch:
    """One search with the extras the page needs. Raises SearchError for bad input."""
    cfg = load_config()
    notes: List[str] = []
    settings = LLMSettings.from_config(cfg, enabled=True if use_llm_mapper else None)
    response = run_search(
        SearchRequest(query=query, mode=mode, k=k, corpus=corpus, index_dir=index_dir, llm=settings,
                      patterns=list(patterns), intents=list(intents), weights=list(weights)),
        cfg, notify=notes.append)
    explanations = None
    if explain != "none":
        explanations = explain_results(query, response.results, response.units_by_id, method=explain,
                                       llm=LLMSettings.from_config(cfg, enabled=True), notify=notes.append)
    rows = [result_to_dict(r, response.units_by_id[r.unit_id], 12, (explanations or {}).get(r.unit_id))
            for r in response.results]
    graph, _ = ensure_graph(list(response.units_by_id.values()), index_dir)
    understanding = understand_query(query, mode, response.extra, response.graph_result)
    breakdown = score_breakdown(response.results, understanding["weights"])
    return UISearch(response, understanding, breakdown, rows, graph, notes)


def scan_corpus_candidates(corpus: str, index_dir: str):
    """(candidates, units_by_id, graph) of the SQL-construction scan over a corpus."""
    units, _ = load_corpus(corpus, index_dir, skip_failed=False, rebuild=False)
    graph, _ = ensure_graph(units, index_dir)
    return scan_sql_candidates(units, graph), {u.unit_id: u for u in units}, graph


# --------------------------------------------------------------------------- page


def _stretch(draw, *args, **kwargs):
    """Call a Streamlit drawing function so that it fills the width, across Streamlit versions."""
    try:
        return draw(*args, width="stretch", **kwargs)
    except TypeError:
        return draw(*args, use_container_width=True, **kwargs)


def _expected_panel(st, demo: Dict[str, Any], result_names: Optional[List[str]] = None) -> None:
    kind = demo["kind"]
    wanted = ", ".join(demo["expected"]) or "nothing"
    head = {"works": "Expected top answers", "partial": "Expected (imperfect list)",
            "limit": "Known limitation", "empty": "Expected"}[kind]
    st.markdown(f"**{head}:** `{wanted}`  \n{demo['note']}")
    if result_names is None:
        return
    if kind in ("works", "partial"):
        hit = bool(result_names) and result_names[0] in demo["expected"]
        (st.success if hit else st.error)(f"Top result: `{result_names[0] if result_names else '(none)'}` "
                                          + ("matches the expectation." if hit else "does not match the expectation."))
    elif kind == "limit":
        st.warning("This query is a documented failure on purpose: "
                   + ("the system misses the expected function." if not result_names or result_names[0] not in demo["expected"]
                      else "the system now finds it (update the documentation)."))
    else:
        (st.success if not result_names else st.error)("Nothing returned, as expected." if not result_names else "Unexpected results.")


def _render_understanding(st, info: Dict[str, Any]) -> None:
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**How the query was read**")
        if not info["uses_graph"]:
            st.caption(f"Mode `{info['mode']}` does not use the call graph.")
        elif info["intents"]:
            for item in info["intents"]:
                st.markdown(f"- relationship **`{item['name']}`**: {item['description']}")
            trace = info["trace"]
            words = {"validation": "validation words", "database": "database words", "file": "file words",
                     "negation": "negation words", "recursion": "recursion words", "injection": "injection words"}
            matched = [f"{label}: " + ", ".join(f"`{w}`" for w in trace[key]) for key, label in words.items() if trace[key]]
            if matched:
                st.caption("Triggered by " + "; ".join(matched))
        else:
            st.markdown("- no relationship the call graph can express")
        if info["graph_note"]:
            st.info(info["graph_note"])
        if info["structure"]:
            st.markdown("**Structure asked for (AST)**")
            for line in info["structure"]:
                st.markdown(f"- {line}")
    with right:
        st.markdown("**Signals in the ranking**")
        if info["weights"]:
            for signal in SIGNAL_ORDER:
                if signal in info["weights"]:
                    st.markdown(f"- {SIGNAL_LABELS[signal]}: weight **{info['weights'][signal]:.2f}**")
            st.caption("A signal with nothing to say about this query, or with weight 0, is left out and the rest are rescaled.")
        else:
            st.caption("Single-signal mode: results are ordered by the one score.")


def _render_breakdown(st, ui: UISearch) -> None:
    import altair as alt

    long = breakdown_long(ui.breakdown)
    if not long:
        return
    domain = [SIGNAL_LABELS.get(s, s) for s in (*SIGNAL_ORDER, "score")]
    chart = alt.Chart(alt.Data(values=long)).mark_bar().encode(
        y=alt.Y("result:N", sort=None, title=None),
        x=alt.X("contribution:Q", title="score contribution = weight x signal score"),
        color=alt.Color("signal:N", scale=alt.Scale(domain=domain), title="signal"),
        tooltip=["result:N", "signal:N", alt.Tooltip("contribution:Q", format=".3f")],
    ).properties(height=max(120, 34 * len(ui.breakdown)))
    _stretch(st.altair_chart, chart)
    if ui.response.results:
        first = ui.breakdown[0]
        if first["contributions"] and "score" not in first["contributions"]:
            parts = " + ".join(f"{s} {first[s]:.2f} x {ui.understanding['weights'][s]:.2f}" for s in first["contributions"])
            st.caption(f"#1 {first['name']}: {parts} = {first['final']:.3f}")


def _search_tab(st, opts: Dict[str, Any]) -> None:
    query = st.session_state.get("query", "").strip()
    demo = next((d for d in DEMO_QUERIES if d["query"] == query), None)
    if not query:
        st.info("Type a query, or pick an example in the sidebar, for instance *queries that run without checking their input*.")
        return
    try:
        with st.spinner("Searching..."):
            ui = run_ui_search(query, opts["mode"], opts["k"], opts["corpus"], opts["index_dir"], opts["explain"],
                               opts["use_llm_mapper"], opts["patterns"], opts["intents"], opts["weights"])
    except SearchError as exc:
        st.error(str(exc))
        return
    names = [r.unit_id.split("::", 1)[-1] for r in ui.response.results]
    if demo:
        _expected_panel(st, demo, names)
    st.subheader("1. How the query was understood")
    _render_understanding(st, ui.understanding)
    st.subheader("2. Ranking and score breakdown")
    st.caption(f"{len(ui.rows)} of {ui.response.total_units} units shown")
    if not ui.rows:
        st.warning("No results.")
        return
    _render_breakdown(st, ui)
    st.subheader("3. Evidence graph")
    focus_options = ["All results"] + [r.unit_id for r in ui.response.results]
    focus = st.selectbox("Highlight the evidence of", focus_options, key="focus")
    context = st.checkbox("Show the other calls and markers of these functions", value=False, key="context")
    dot = evidence_graph_dot(ui.graph, ui.response.results, ui.response.graph_result,
                             None if focus == "All results" else focus, context)
    if ui.response.graph_result is None:
        st.caption("This mode has no call-graph evidence; switch to `text_graph` or `text_ast_graph` to see it.")
    elif not ui.response.graph_result.edges:
        st.caption("No call-graph evidence for this query: the graph signal is empty.")
    _stretch(st.graphviz_chart, dot)
    st.caption(LEGEND)
    st.subheader("4. Results")
    for row in ui.rows:
        with st.expander(f"{row['unit_id']}  -  score {row['final_score']:.3f}", expanded=row is ui.rows[0]):
            if "explanation" in row:
                st.write(row["explanation"]["summary"])
            st.code(row["excerpt"], language="python")
            st.markdown("\n".join(f"- {line}" for line in row["evidence"]))
    if ui.notes:
        with st.expander("Log"):
            st.text("\n".join(ui.notes))


def _security_tab(st, opts: Dict[str, Any]) -> None:
    st.markdown(f"**Pattern:** {PATTERN_QUERY}.")
    st.warning(DISCLAIMER)
    try:
        candidates, units_by_id, _ = scan_corpus_candidates(opts["corpus"], opts["index_dir"])
    except SearchError as exc:
        st.error(str(exc))
        return
    if not candidates:
        st.success("No candidates found in this corpus.")
    else:
        rows = candidate_rows(candidates)
        st.dataframe(rows, hide_index=True)
        for cand in candidates:
            with st.expander(f"{cand.unit_id}  -  {cand.level} ({cand.score:.2f})"):
                st.code(units_by_id[cand.unit_id].source_text, language="python")
                st.markdown("\n".join(f"- {line}" for line in cand.evidence))
    with st.expander("What is not modelled"):
        st.markdown("\n".join(f"- {line}" for line in NOT_MODELLED))


def _graph_tab(st, opts: Dict[str, Any]) -> None:
    try:
        units, _ = load_corpus(opts["corpus"], opts["index_dir"], skip_failed=False, rebuild=False)
    except SearchError as exc:
        st.error(str(exc))
        return
    graph, _ = ensure_graph(units, opts["index_dir"])
    calls = sum(e.relation == "calls" for e in graph.edges)
    st.caption(f"{len(graph.nodes)} functions, {calls} call edges, {len(graph.edges) - calls} marker edges, "
               f"{len(graph.ambiguous)} ambiguous calls (no edge).")
    files = ["(all files)"] + sorted({n.file_path for n in graph.nodes.values()})
    chosen_file = st.selectbox("File", files, key="graph_file")
    unit = st.selectbox("Inspect a function", ["(none)"] + sorted(graph.nodes), key="graph_unit")
    dot = full_graph_dot(graph, None if chosen_file == files[0] else chosen_file, None if unit == "(none)" else unit)
    _stretch(st.graphviz_chart, dot)
    st.caption(LEGEND)
    if unit != "(none)":
        card = unit_card(graph, unit)
        st.markdown(f"**{unit}**  ({card['parse_status']})")
        st.markdown("- calls: " + (", ".join(f"`{t}` (line {ln})" for t, ln in card["calls"]) or "none"))
        st.markdown("- called by: " + (", ".join(f"`{s}` (line {ln})" for s, ln in card["called_by"]) or "none"))
        st.markdown("- markers: " + (", ".join(f"`{m}` (line {ln})" for m, ln, _ in card["markers"]) or "none"))


METRIC_CHOICES = {"nDCG@k": "nDCG@K", "MRR": "MRR", "P@k": "Precision@K", "R@k": "Recall@K", "hit@k": "Hit@K (any relevant in top K)"}
OUTCOME_WORDS = {"win": "better than BM25", "tie": "same as BM25", "loss": "worse than BM25"}


def _bar_chart(st, rows: List[Dict[str, Any]], value_title: str, color_domain: Sequence[str]) -> None:
    import altair as alt

    chart = alt.Chart(alt.Data(values=rows)).mark_bar().encode(
        y=alt.Y("label:N", sort=color_domain, title=None),
        x=alt.X("value:Q", title=value_title, scale=alt.Scale(domain=[min(0, min(r["value"] for r in rows)), 1])),
        color=alt.Color("label:N", scale=alt.Scale(domain=list(color_domain)), legend=None),
        tooltip=["label:N", alt.Tooltip("value:Q", format=".3f")],
    ).properties(height=34 * len(rows) + 20)
    _stretch(st.altair_chart, chart)


def _short_unit(unit_id: str) -> str:
    return unit_id.split("::", 1)[-1]


def _results_tab(st) -> None:
    run = rd.load_results()
    if run is None:
        st.info("No experiment results found in `experiments/runs/final`. Produce them with "
                "`experiments/run_experiments.sh final` (see README_STEP18.md).")
        return
    left, middle, right, metric_col = st.columns([2, 1, 2, 2])
    split = {"Test split": "test", "Development split": "dev"}[left.radio("Queries", ["Test split", "Development split"], key="res_split")]
    k = middle.select_slider("K", options=[1, 3, 5], value=3, key="res_k")
    category = {"All queries": "all", "Lexical": "lexical", "Relationship": "relationship"}[
        right.selectbox("Query type", ["All queries", "Lexical", "Relationship"], key="res_category")]
    metric = metric_col.selectbox("Metric", list(METRIC_CHOICES), format_func=METRIC_CHOICES.get, key="res_metric")
    st.caption(rd.split_note(split))
    if run.benchmark_matches_lock is False:
        st.error("The benchmark has changed since this run: these results no longer match the current queries and labels.")
    elif run.benchmark_matches_lock:
        st.caption("These results were produced on the frozen benchmark, which has not changed since.")

    rows = rd.metric_rows(run, split, category, k)
    n = rows[0]["n"] if rows else 0
    st.subheader(f"1. Variants compared ({n} queries)")
    _bar_chart(st, [{"label": r["label"], "value": r[metric]} for r in rows], f"{METRIC_CHOICES[metric]} at K = {k}",
               [rd.VARIANT_LABELS[v] for v in rd.VARIANT_ORDER])
    st.dataframe([{"variant": r["label"], **{METRIC_CHOICES[m]: round(r[m], 3) for m in METRIC_CHOICES}} for r in rows],
                 hide_index=True)

    st.subheader("2. What each signal contributes (ablation)")
    ablation = rd.ablation_rows(run, split, category, k, metric)
    _bar_chart(st, [{"label": r["label"], "value": r["value"]} for r in ablation], f"{METRIC_CHOICES[metric]} at K = {k}",
               [rd.VARIANT_LABELS[v] for v in rd.ABLATIONS])
    st.dataframe([{"variant": r["label"], METRIC_CHOICES[metric]: round(r["value"], 3), "change vs full": f"{r['delta']:+.3f}"}
                  for r in ablation], hide_index=True)
    st.caption("Removing a signal sets its weight to 0 and leaves the others as tuned. A larger drop means the signal matters more.")

    st.subheader("3. Query by query against BM25")
    paired = rd.paired_rows(run, split, category, k)
    st.dataframe([{"variant": r["label"], "queries": r["n"], "better": r["wins"], "same": r["ties"], "worse": r["losses"],
                   "mean nDCG change": round(r["mean_diff"], 3), "sign-test p": round(r["p_value"], 3)} for r in paired],
                 hide_index=True)
    st.caption("Counts are queries for which the variant ranked better, the same or worse than BM25 (nDCG@K). The p-value is an "
               "exact sign test; with this few queries it has little power, so read the counts.")

    st.subheader("4. Where the full model improves or fails")
    outcomes = rd.query_outcomes(run, split, rd.FULL, rd.BASELINE, k)
    if category != "all":
        outcomes = [o for o in outcomes if o["category"] == category]
    groups = rd.error_analysis(outcomes)
    titles = {"improved": "Improved over BM25", "regressed": "Worse than BM25", "solved": "Already right with BM25 (no change)",
              "unsolved": "Not fully solved by the full model"}
    for key in ("improved", "regressed", "unsolved", "solved"):
        items = groups[key]
        with st.expander(f"{titles[key]}: {len(items)}", expanded=key in ("improved", "unsolved")):
            if not items:
                st.caption("none")
            for o in items:
                where = (f"first correct answer: rank {o['baseline_rank'] or 'none'} with BM25, "
                         f"rank {o['variant_rank'] or 'none'} with the full model")
                st.markdown(f"- **{o['query_id']}** {o['query']} ({o['category']}): {where}; nDCG {o['baseline_ndcg']:.2f} -> {o['variant_ndcg']:.2f}")

    st.subheader("5. Inspect one query")
    order = {"win": 0, "loss": 1, "tie": 2}
    listing = sorted(outcomes, key=lambda o: (order[o["outcome"]], o["query_id"]))
    labels = {o["query_id"]: f"{o['query_id']} [{OUTCOME_WORDS[o['outcome']]}] {o['query']}" for o in listing}
    if not listing:
        return
    chosen = st.selectbox("Query", list(labels), format_func=labels.get, key="result_query")
    detail = rd.query_detail(run, chosen, k)
    st.markdown(f"**{detail['query']}**  ({detail['category']}, {detail['split']} split"
                + (f", paraphrase group `{detail['group']}`" if detail["group"] else "") + ")")
    st.markdown("Correct answers: " + ", ".join(f"`{_short_unit(u)}`" for u in detail["relevant"]))
    if detail["notes"]:
        st.caption(detail["notes"])
    table = []
    for v in detail["variants"]:
        row: Dict[str, Any] = {"variant": v["label"], "first correct at rank": str(v["first_relevant"] or "-"), "nDCG": round(v["ndcg"], 2)}
        for rank in range(1, k + 1):
            item = v["ranking"][rank - 1] if rank <= len(v["ranking"]) else None
            row[f"rank {rank}"] = "" if item is None else ("[correct] " if item["relevant"] else "[wrong] ") + _short_unit(item["unit_id"])
        table.append(row)
    st.dataframe(table, hide_index=True)


def _apply_example() -> None:  # pragma: no cover - exercised through streamlit
    import streamlit as st

    label = st.session_state.get("example")
    demo = next((d for d in DEMO_QUERIES if d["label"] == label), None)
    if demo:
        st.session_state["query"] = demo["query"]


def main() -> None:
    import streamlit as st

    cfg = load_config()
    st.set_page_config(page_title="StructSearch", layout="wide")
    st.title("StructSearch")
    st.caption("Structure-aware code search: BM25 text, AST structure and a call graph, fused and explained.")
    with st.sidebar:
        st.selectbox("Example queries", ["(none)"] + [d["label"] for d in DEMO_QUERIES], key="example", on_change=_apply_example,
                     help="Fills the query and shows the answer expected from the code.")
        k = st.slider("Results", 1, 20, min(int(cfg["top_k"]), 5), key="k")
        corpus = st.text_input("Corpus", cfg["corpus_path"], key="corpus")
        index_dir = st.text_input("Index folder", cfg["index_dir"], key="index_dir")
        st.caption(f"Ranking: `{MODE}` (BM25 text + AST structure + call graph).")
    opts = {"mode": MODE, "k": k, "corpus": corpus, "index_dir": index_dir, "explain": "template", "intents": [],
            "weights": [], "use_llm_mapper": False, "patterns": []}
    st.text_input("Query", key="query", placeholder="function that opens a file without closing it")
    search_tab, security_tab, graph_tab, results_tab = st.tabs(["Search", "Security candidates", "Call graph", "Results"])
    with search_tab:
        _search_tab(st, opts)
    with security_tab:
        _security_tab(st, opts)
    with graph_tab:
        _graph_tab(st, opts)
    with results_tab:
        _results_tab(st)


if __name__ == "__main__":  # pragma: no cover
    main()
