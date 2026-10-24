"""Data behind the Streamlit app: plain functions that turn a search response into what the page shows.

Nothing here imports Streamlit, so it is unit-tested directly. Every number and edge shown comes from the
objects the ranker used (the fusion weights, the per-signal scores of each result, the graph edges behind the
graph evidence), not from a re-computation for display.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from structsearch.graph import (
    INTENT_DOC,
    REL_CALLS,
    REL_USES_API,
    CodeGraph,
    GraphEdge,
    GraphResult,
    graph_intent_trace,
)
from structsearch.schemas import CodeUnit, RankedResult

FUSED_MODES = ("text_ast", "text_graph", "text_ast_graph", "hybrid")
SIGNAL_LABELS = {"text": "text (BM25)", "dense": "dense (embeddings)", "structural": "structure (AST)", "graph": "call graph"}
SIGNAL_ORDER = ("text", "dense", "structural", "graph")

# Colours: kept in one place so the legend and the graph agree.
COLOR_EVIDENCE = "#d62728"
COLOR_CONTEXT = "#9aa0a6"
MARKER_COLORS = {"db": "#f4a261", "file": "#8ecf9a", "validation": "#b39ddb"}
NODE_RESULT_LOW, NODE_RESULT_HIGH = (222, 235, 247), (49, 130, 189)  # light -> dark blue by score
LEGEND = (
    "**Legend** — blue box: a returned function (darker = higher score, #rank); white dashed box: a function "
    "reached through a call; diamond: an API/validation marker (orange database, green file, purple validation); "
    "solid arrow: a call; dashed arrow: a marker found in the code; red: evidence the ranking used; grey: other "
    "calls and markers of the same functions."
)

# Demo queries with the answer read from the code. kind: works (top result is expected), partial (right top result,
# imperfect list), limit (known failure, shown on purpose), empty (nothing relevant exists).
DEMO_QUERIES: List[Dict[str, Any]] = [
    {"label": "Without validation (graph beats BM25)", "query": "queries that run without checking their input",
     "expected": ["find_user_unsafe", "count_rows"], "kind": "works",
     "note": "BM25 ranks validate_user_input first, which never queries the database. The graph finds the two functions "
             "that run SQL with no validation step."},
    {"label": "Recursion (BM25 finds nothing)", "query": "function that calls itself",
     "expected": ["factorial", "inorder_traverse"], "kind": "works",
     "note": "No word of the query appears in the code; the call graph supplies the self-call edges."},
    {"label": "Validate before database access", "query": "validate user input before database access",
     "expected": ["get_user"], "kind": "works",
     "note": "get_user calls the validator (line 12) before execute (line 13)."},
    {"label": "Database access without validation", "query": "database access without validation",
     "expected": ["find_user_unsafe", "count_rows"], "kind": "works",
     "note": "get_user validates first, so it is not an answer."},
    {"label": "Which functions touch the database", "query": "which functions touch the database",
     "expected": ["get_user", "find_user_unsafe", "count_rows"], "kind": "works",
     "note": "BM25 returns only get_user; the db:execute markers give all three."},
    {"label": "Paraphrase: sanitize then query", "query": "sanitize the input and then run a sql query",
     "expected": ["get_user"], "kind": "works", "note": "Different wording, same relationship."},
    {"label": "File without error handling", "query": "opens a file without error handling",
     "expected": ["read_lines", "write_log"], "kind": "works",
     "note": "read_config_safe has a try/except, so it is not an answer."},
    {"label": "Error handling around file access", "query": "exception handling around file access",
     "expected": ["read_config_safe"], "kind": "works", "note": "Structure (try/except) and text agree."},
    {"label": "Loop structure", "query": "function with a while loop", "expected": ["count_nodes"], "kind": "works",
     "note": "No call-graph relationship in this query; the graph stays out."},
    {"label": "Plain functionality (graph stays out)", "query": "convert camel case name to snake case",
     "expected": ["camel_to_snake"], "kind": "works", "note": "Ranked exactly like BM25."},
    {"label": "Log file", "query": "append a message to a log file", "expected": ["write_log"], "kind": "works",
     "note": "The word 'file' also triggers the file-access relationship; a harmless extra signal here."},
    {"label": "JSON config", "query": "read a json file and handle bad json", "expected": ["read_config_safe"],
     "kind": "works", "note": "read_config_safe catches JSONDecodeError."},
    {"label": "Paraphrase without the usual words", "query": "make sure the argument is acceptable before it reaches the database layer",
     "expected": ["get_user"], "kind": "partial",
     "note": "Right top result, but the word list reads this only as plain database access, so all three database "
             "functions are listed."},
    {"label": "Known limitation", "query": "function that calls another function defined in the same file",
     "expected": ["get_user"], "kind": "limit",
     "note": "Every mode misses get_user: the mapper reads the word 'file' as file access and the graph has no "
             "relationship for this wording."},
    {"label": "Nothing relevant", "query": "payment gateway timeout retry", "expected": [], "kind": "empty",
     "note": "No function matches, and the system returns nothing."},
]


# --------------------------------------------------------------------------- understanding the query


def understand_query(query: str, mode: str, extra: Mapping[str, Any], graph_result: Optional[GraphResult]) -> Dict[str, Any]:
    """What the system made of the query: relationships (with the words that triggered them), structure, signals."""
    uses_graph = graph_result is not None
    out: Dict[str, Any] = {"mode": mode, "uses_graph": uses_graph, "intents": [], "trace": None, "graph_note": None,
                           "structure": [], "signals": [], "weights": {}}
    if uses_graph:
        trace = graph_intent_trace(query)
        intents = graph_result.intents or trace["intents"]
        out["trace"] = trace
        out["intents"] = [{"name": i, "description": INTENT_DOC[i]} for i in intents]
        if not graph_result.intents:
            out["graph_note"] = "No relationship the call graph can express was found in the query: the graph is left out."
        elif not graph_result.scores:
            out["graph_note"] = "The relationship was found, but no function in the corpus has it."
    profile = extra.get("profile")
    if profile:
        out["structure"] = [c.get("reason") or f"{c.get('op')} {'+'.join(c.get('features', []))}" for c in profile.get("constraints", [])]
        out["structure"] += [p.get("reason") or p.get("text", "") for p in profile.get("patterns", [])]
    fusion = extra.get("fusion")
    if fusion:
        out["signals"] = list(fusion.get("signals", []))
        out["weights"] = dict(fusion.get("weights", {}))
    return out


# --------------------------------------------------------------------------- score breakdown


def score_breakdown(results: Sequence[RankedResult], weights: Mapping[str, float]) -> List[Dict[str, Any]]:
    """One row per result with each signal's contribution (weight x normalized score); they add up to final_score.

    Without fusion weights (bm25, dense, structural, like) each row has just the final score."""
    rows: List[Dict[str, Any]] = []
    for rank, res in enumerate(results, 1):
        row: Dict[str, Any] = {"rank": rank, "unit_id": res.unit_id, "name": res.unit_id.split("::", 1)[-1],
                               "final": res.final_score, "contributions": {}}
        parts = {"text": res.text_score, "dense": res.dense_score, "structural": res.structural_score, "graph": res.graph_score}
        for signal in SIGNAL_ORDER:
            if signal in weights and parts[signal] is not None:
                row["contributions"][signal] = weights[signal] * parts[signal]
                row[signal] = parts[signal]
        if not weights:
            row["contributions"]["score"] = res.final_score
        rows.append(row)
    return rows


def breakdown_long(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Rows for a stacked bar chart: one record per (result, signal)."""
    return [{"result": f"#{r['rank']} {r['name']}", "signal": SIGNAL_LABELS.get(s, s), "contribution": v, "rank": r["rank"]}
            for r in rows for s, v in r["contributions"].items()]


# --------------------------------------------------------------------------- DOT graphs


def _q(text: str) -> str:
    """A DOT double-quoted string."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _blend(score: float) -> str:
    t = max(0.0, min(1.0, score))
    r, g, b = (round(lo + (hi - lo) * t) for lo, hi in zip(NODE_RESULT_LOW, NODE_RESULT_HIGH))
    return f"#{r:02x}{g:02x}{b:02x}"


def _text_color(fill: str) -> str:
    r, g, b = (int(fill[i:i + 2], 16) for i in (1, 3, 5))
    return "white" if (0.299 * r + 0.587 * g + 0.114 * b) < 140 else "black"


def _marker_category(label: str) -> str:
    return label.split(":", 1)[0]


class _Dot:
    def __init__(self) -> None:
        self.lines: List[str] = ["digraph G {", '  rankdir=LR; bgcolor="transparent";',
                                 '  node [fontname="Helvetica", fontsize=11]; edge [fontname="Helvetica", fontsize=9];']
        self.ids: Dict[str, str] = {}

    def node_id(self, key: str) -> str:
        return self.ids.setdefault(key, f"n{len(self.ids)}")

    def add(self, line: str) -> None:
        self.lines.append("  " + line)

    def unit_node(self, key: str, label: str, fill: Optional[str], failed: bool = False) -> None:
        if failed:
            self.add(f"{self.node_id(key)} [label={_q(label)}, shape=box, style=filled, fillcolor=\"#e0e0e0\", color=\"#9e9e9e\"];")
        elif fill:
            self.add(f"{self.node_id(key)} [label={_q(label)}, shape=box, style=\"rounded,filled\", fillcolor=\"{fill}\", "
                     f"fontcolor=\"{_text_color(fill)}\", color=\"#1f4e79\"];")
        else:
            self.add(f"{self.node_id(key)} [label={_q(label)}, shape=box, style=\"rounded,dashed\", color=\"#607d8b\"];")

    def marker_node(self, label: str) -> None:
        fill = MARKER_COLORS.get(_marker_category(label), "#dddddd")
        self.add(f"{self.node_id('marker:' + label)} [label={_q(label)}, shape=diamond, style=filled, fillcolor=\"{fill}\"];")

    def edge(self, src: str, dst: str, edge: GraphEdge, highlight: Optional[bool]) -> None:
        color = COLOR_EVIDENCE if highlight else COLOR_CONTEXT
        style = "dashed" if edge.relation == REL_USES_API else "solid"
        width = 2.6 if highlight else 1.0
        self.add(f"{self.node_id(src)} -> {self.node_id(dst)} [label={_q('line ' + str(edge.line))}, color=\"{color}\", "
                 f"fontcolor=\"{color}\", style={style}, penwidth={width}];")

    def text(self) -> str:
        return "\n".join(self.lines + ["}"])


def _short(graph: CodeGraph, unit_id: str) -> str:
    node = graph.nodes.get(unit_id)
    return f"{node.qualname}\n{node.file_path}" if node else unit_id


def _edge_key(edge: GraphEdge) -> Tuple[str, str, str, int]:
    return (edge.source, edge.target, edge.relation, edge.line)


def evidence_graph_dot(
    graph: CodeGraph,
    results: Sequence[RankedResult],
    graph_result: Optional[GraphResult] = None,
    focus: Optional[str] = None,
    show_context: bool = False,
    max_nodes: int = 40,
) -> str:
    """DOT for the functions the search returned and the graph edges its evidence used.

    `focus` (a unit_id) highlights only that result's evidence; otherwise every result's evidence is highlighted.
    `show_context` adds the other call and marker edges of the returned functions in grey."""
    dot = _Dot()
    returned = {r.unit_id: (rank, r.final_score) for rank, r in enumerate(results, 1)}
    evidence_edges: Dict[Tuple[str, str, str, int], Tuple[GraphEdge, bool]] = {}
    for unit_id, edges in (graph_result.edges.items() if graph_result else ()):
        if unit_id not in returned:
            continue
        for edge in edges:
            hot = focus is None or unit_id == focus
            key = _edge_key(edge)
            evidence_edges[key] = (edge, hot or evidence_edges.get(key, (edge, False))[1])
    context: Dict[Tuple[str, str, str, int], GraphEdge] = {}
    if show_context:
        for unit_id in returned:
            for edge in graph.edges_from(unit_id):
                if _edge_key(edge) not in evidence_edges:
                    context[_edge_key(edge)] = edge

    units: List[str] = list(returned)
    markers: List[str] = []
    for edge, _ in list(evidence_edges.values()) + [(e, False) for e in context.values()]:
        for end in (edge.source, edge.target):
            if edge.relation == REL_USES_API and end == edge.target:
                if end not in markers:
                    markers.append(end)
            elif end not in units:
                units.append(end)
    shown_units = units[:max_nodes]
    for unit_id in shown_units:
        node = graph.nodes.get(unit_id)
        failed = bool(node and node.parse_status == "failed")
        if unit_id in returned:
            rank, score = returned[unit_id]
            dot.unit_node(unit_id, f"#{rank} {_short(graph, unit_id)}\nscore {score:.2f}", _blend(score), failed)
        else:
            dot.unit_node(unit_id, _short(graph, unit_id), None, failed)
    for label in markers:
        dot.marker_node(label)
    for edge, hot in evidence_edges.values():
        if edge.source in shown_units and (edge.target in shown_units or edge.relation == REL_USES_API):
            dot.edge(edge.source, ("marker:" + edge.target) if edge.relation == REL_USES_API else edge.target, edge, hot)
    for edge in context.values():
        if edge.source in shown_units and (edge.target in shown_units or edge.relation == REL_USES_API):
            dot.edge(edge.source, ("marker:" + edge.target) if edge.relation == REL_USES_API else edge.target, edge, False)
    return dot.text()


def full_graph_dot(graph: CodeGraph, file_filter: Optional[str] = None, highlight: Optional[str] = None) -> str:
    """The whole call graph (or one file's functions), grouped by file; `highlight` marks one function and its edges."""
    dot = _Dot()
    units = [u for u, n in graph.nodes.items() if file_filter in (None, "", n.file_path)]
    by_file: Dict[str, List[str]] = {}
    for unit_id in units:
        by_file.setdefault(graph.nodes[unit_id].file_path, []).append(unit_id)
    for index, (file_path, members) in enumerate(sorted(by_file.items())):
        dot.add(f"subgraph cluster_{index} {{ label={_q(file_path)}; color=\"#bdbdbd\"; style=rounded;")
        for unit_id in sorted(members):
            node = graph.nodes[unit_id]
            fill = "#ffe0e0" if unit_id == highlight else "#eaf1f8"
            dot.unit_node(unit_id, node.qualname, None if node.parse_status == "failed" else fill, node.parse_status == "failed")
        dot.add("}")
    markers: List[str] = []
    for edge in graph.edges:
        if edge.source not in units:
            continue
        involved = highlight in (edge.source, edge.target)
        if edge.relation == REL_USES_API:
            if edge.target not in markers:
                markers.append(edge.target)
                dot.marker_node(edge.target)
            dot.edge(edge.source, "marker:" + edge.target, edge, involved if highlight else None)
        elif edge.target in units:
            dot.edge(edge.source, edge.target, edge, involved if highlight else None)
    return dot.text()


def unit_card(graph: CodeGraph, unit_id: str) -> Dict[str, Any]:
    """What the graph knows about one function: calls, callers and markers (with lines)."""
    node = graph.nodes.get(unit_id)
    return {
        "unit_id": unit_id,
        "found": node is not None,
        "parse_status": node.parse_status if node else None,
        "calls": [(e.target, e.line) for e in graph.edges_from(unit_id, REL_CALLS)],
        "called_by": [(e.source, e.line) for e in graph.edges_to(unit_id, REL_CALLS)],
        "markers": [(e.target, e.line, e.detail) for e in graph.markers_of(unit_id)],
    }


# --------------------------------------------------------------------------- security candidates


def candidate_rows(candidates: Sequence[Any]) -> List[Dict[str, Any]]:
    """Table rows for the security tab (one per candidate): level, score, the source and the sink line."""
    rows = []
    for c in candidates:
        pick = lambda prefix: next((l[len(prefix):] for l in c.evidence if l.startswith(prefix)), "")
        rows.append({"function": c.unit_id, "level": c.level, "score": round(c.score, 2), "hops": c.hops,
                     "source": pick("source: "), "sink": pick("sink: ")})
    return rows


def escape_html(text: str) -> str:
    return html.escape(str(text))
