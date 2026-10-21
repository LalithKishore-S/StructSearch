"""Bounded vulnerability-pattern query: candidate paths from input to SQL text construction.

Pattern (PATTERN_QUERY): input reaches the text of an SQL statement that is executed, and no
validation precedes it. The scan reports candidates for human review. It does NOT establish that a
vulnerability exists: nothing here is data-flow analysis.

What is modelled (syntax of one function at a time, plus one call-graph step)
  source      a parameter of the function (the caller is unknown), or an external-input expression:
              input(...), request.* (e.g. request.args.get), sys.argv, os.environ
  carrying    a local assigned from an expression that uses a source (`b = a.strip()`), followed in
              source order; assigning a source-free value clears it (flow-insensitive: the state at the
              end of the function is used for an expression written directly inside the execute call)
  construction  SQL text built from a source or validated value by `+`, `%`, an f-string or `.format()`,
              where a string constant in the expression contains an SQL keyword (select, insert, update,
              delete, drop, create, alter, where, from, values); `q += value` on a local that holds SQL text
  sink        a `db:execute` marker call (execute/executemany/executescript) whose first argument is the
              built text (directly or through a local), or a parameter / carrier of input executed as is
  validation  a validation step (`validation:validate` marker) before the sink, or the built value coming
              from the result of a call named like validation; reported, scored lower, never treated as safe
  paths       a function that passes its own input as an argument to a candidate function (positional or
              keyword), up to 2 calls up; each hop is a call-graph edge

Score: 1.0 external source, 0.8 parameter; x0.6 when a parameter is executed as is; x0.3 when the built
value came through a validation call, else x0.5 when a validation step precedes the sink; x0.7 per call
hop (x0.5 more when the caller validates before the call). Level: high >= 0.7, medium >= 0.35, else low.

What is NOT modelled (NOT_MODELLED): data flow across statements beyond simple assignment, loops and
branches (a validation in one branch counts as a validation step), whether a validation is effective,
parameterized queries built elsewhere, SQL assembled with join/append/ORMs/helper functions, input arriving
through attributes, containers or *args/**kwargs, aliases and indirect calls, other languages.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from structsearch.graph.markers import DEFAULT_MARKERS, name_words
from structsearch.graph.model import REL_CALLS, CodeGraph
from structsearch.ingestion.segmenter import parse_unit
from structsearch.schemas import PARSEABLE, CodeUnit, RankedResult

PATTERN_QUERY = "possible paths from external input to SQL query construction with weak or missing validation"
DISCLAIMER = "note: candidate for human review, not confirmed; syntax-level evidence only, no data-flow analysis"
NOT_MODELLED = [
    "data flow across statements beyond simple assignment; loops and branches are not followed",
    "whether a validation step is effective, or covers the path to the query",
    "parameterized queries built in another function or by a library",
    "SQL assembled with join/append, ORMs or helper functions",
    "input arriving through attributes, containers, *args/**kwargs or callbacks",
    "aliases, dynamic dispatch and indirect calls",
    "sources other than parameters, input(), request.*, sys.argv and os.environ",
    "languages other than Python",
]

SCORE_EXTERNAL, SCORE_PARAMETER = 1.0, 0.8
FACTOR_DIRECT, FACTOR_VALIDATED_VALUE, FACTOR_VALIDATION_BEFORE = 0.6, 0.3, 0.5
FACTOR_HOP, FACTOR_CALLER_VALIDATES = 0.7, 0.5
MAX_HOPS = 2
LEVELS = (("high", 0.7), ("medium", 0.35), ("low", 0.0))

_SQL_WORDS = re.compile(r"\b(select|insert|update|delete|drop|create|alter|where|from|values)\b", re.I)
_EXECUTE = ("execute", "executemany", "executescript")
_EXTERNAL_PREFIXES = ("request.", "flask.request.", "sys.argv", "os.environ")
_VALIDATION_WORDS = next(m for m in DEFAULT_MARKERS if m.category == "validation").name_words
_SELF = ("self", "cls")


def level_of(score: float) -> str:
    return next(name for name, floor in LEVELS if score >= floor)


@dataclass
class Source:
    kind: str  # "parameter" or "external"
    text: str  # parameter name or the external expression
    line: int = 0
    origin: str = ""  # parameter the value comes from (for call paths)


@dataclass
class Candidate:
    unit_id: str
    score: float
    hops: int
    evidence: List[str]
    tainted_params: Set[str] = field(default_factory=set)  # parameters of this unit that carry the input

    @property
    def level(self) -> str:
        return level_of(self.score)


# --------------------------------------------------------------------------- per-unit facts


class _Unit:
    """Syntax facts of one unit: parameters, carried input, calls."""

    def __init__(self, unit: CodeUnit, graph: CodeGraph):
        self.unit = unit
        self.func = parse_unit(unit)
        self.qualname = graph.nodes[unit.unit_id].qualname
        self.first = min([self.func.lineno] + [d.lineno for d in self.func.decorator_list])
        args = self.func.args
        self.params = [a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
        self.data_params = [p for p in self.params if p not in _SELF]
        self.tainted: Dict[str, Source] = {
            p: Source("parameter", p, self.line(self.func), p) for p in self.data_params}
        self.validated: Dict[str, Tuple[str, int, Source]] = {}
        self.sql_vars: Set[str] = set()
        self.built: Dict[str, Tuple[str, ast.AST, int]] = {}  # variable -> (kind, node, line) of the SQL text
        self.validation_lines = sorted(e.line for e in graph.markers_of(unit.unit_id) if e.target == "validation:validate")
        self._walk()

    def line(self, node: ast.AST) -> int:
        return self.unit.start_line + (node.lineno - self.first)

    # ---- sources inside an expression

    def external_in(self, expr: ast.AST) -> Optional[Source]:
        for node in ast.walk(expr):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input":
                return Source("external", "input()", self.line(node))
            if isinstance(node, ast.Attribute) and ast.unparse(node).startswith(_EXTERNAL_PREFIXES):
                return Source("external", ast.unparse(node), self.line(node))
        return None

    def sources_in(self, expr: ast.AST) -> List[Source]:
        found: List[Source] = []
        external = self.external_in(expr)
        if external:
            found.append(external)
        for node in ast.walk(expr):
            if isinstance(node, ast.Name) and node.id in self.tainted:
                src = self.tainted[node.id]
                if all((s.kind, s.text, s.origin) != (src.kind, src.text, src.origin) for s in found):
                    found.append(src)
        return found

    def validated_in(self, expr: ast.AST) -> Optional[Tuple[str, int, Source]]:
        for node in ast.walk(expr):
            if isinstance(node, ast.Name) and node.id in self.validated:
                return self.validated[node.id]
        return None

    # ---- construction of SQL text

    def construction(self, expr: ast.AST) -> Optional[Tuple[str, ast.AST]]:
        """Outermost expression below `expr` that builds SQL text from a source or a validated value."""
        for node in ast.walk(expr):
            kind = self._build_kind(node)
            if kind is None:
                continue
            consts = " ".join(c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str))
            if _SQL_WORDS.search(consts) and (self.sources_in(node) or self.validated_in(node)):
                return kind, node
        return None

    @staticmethod
    def _build_kind(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return "string concatenation"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return "% formatting"
        if isinstance(node, ast.JoinedStr):
            return "f-string"
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)):
            return ".format()"
        return None

    # ---- one pass over assignments in source order

    def _walk(self) -> None:
        statements = [n for n in ast.walk(self.func) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))]
        for node in sorted(statements, key=lambda n: (n.lineno, n.col_offset)):
            value = node.value
            if value is None:
                continue
            targets = [node.target] if not isinstance(node, ast.Assign) else node.targets
            names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            if isinstance(node, ast.AugAssign):
                self._augment(node, names, value)
                continue
            built = self.construction(value)
            if isinstance(value, ast.Call) and self._validating_call(value):
                origin = (self.sources_in(value) or [Source("parameter", "?", 0, "?")])[0]
                for n in names:
                    self.tainted.pop(n, None)
                    self.validated[n] = (ast.unparse(value.func), self.line(value), origin)
                continue
            sources = self.sources_in(value)
            checked = self.validated_in(value)
            for n in names:
                self.tainted.pop(n, None)
                self.validated.pop(n, None)
                self.sql_vars.discard(n)
                self.built.pop(n, None)
                if sources:
                    self.tainted[n] = sources[0]
                elif checked:
                    self.validated[n] = checked
                if built:
                    self.built[n] = (built[0], built[1], self.line(built[1]))
                if self._is_sql_text(value):
                    self.sql_vars.add(n)

    def _augment(self, node: ast.AugAssign, names: List[str], value: ast.AST) -> None:
        if not isinstance(node.op, ast.Add):
            return
        sources, checked = self.sources_in(value), self.validated_in(value)
        for n in names:
            if n in self.sql_vars and (sources or checked):
                self.built[n] = ("string concatenation", node, self.line(node))
                if sources:
                    self.tainted[n] = sources[0]
                else:
                    self.validated[n] = checked  # type: ignore[assignment]

    @staticmethod
    def _is_sql_text(value: ast.AST) -> bool:
        consts = [c.value for c in ast.walk(value) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        return isinstance(value, (ast.Constant, ast.JoinedStr)) and bool(_SQL_WORDS.search(" ".join(consts)))

    @staticmethod
    def _validating_call(call: ast.Call) -> bool:
        func = call.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        return bool(set(name_words(name)) & _VALIDATION_WORDS)

    # ---- sinks

    def executes(self) -> List[ast.Call]:
        calls = [n for n in ast.walk(self.func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in _EXECUTE and n.args]
        return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


# --------------------------------------------------------------------------- direct candidates


def _validation_before(facts: _Unit, line: int) -> Optional[int]:
    return next((v for v in facts.validation_lines if v < line), None)


def _direct(facts: _Unit, unit_id: str) -> Optional[Candidate]:
    best: Optional[Candidate] = None
    for call in facts.executes():
        arg = call.args[0]
        sink_line, detail = facts.line(call), ast.unparse(call.func)
        built = facts.construction(arg)
        via = None
        if built is None and isinstance(arg, ast.Name) and arg.id in facts.built:
            kind, node, _ = facts.built[arg.id]
            built, via = (kind, node), arg.id
        evidence: List[str] = []
        direct_param = False
        if built is not None:
            kind, node = built
            sources = facts.sources_in(node)
            checked = facts.validated_in(node)
            origin = sources[0] if sources else checked[2]
            used = sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                           and (n.id in facts.tainted or n.id in facts.validated)})
            evidence.append(_source_line(origin, facts))
            evidence.append(f"construction: {kind} at line {facts.line(node)} uses {', '.join(repr(u) for u in used)}")
            how = f"via variable '{via}'" if via else "directly"
            evidence.append(f"sink: db:execute at line {sink_line} ({detail}) receives the built text {how}")
        elif isinstance(arg, ast.Name) and arg.id in facts.tainted:
            origin, checked, direct_param = facts.tainted[arg.id], None, True
            evidence.append(_source_line(origin, facts))
            evidence.append(f"sink: db:execute at line {sink_line} ({detail}) receives "
                            f"{'parameter' if arg.id in facts.data_params else 'a value derived from input'} '{arg.id}' directly")
        else:
            continue
        score = SCORE_EXTERNAL if origin.kind == "external" else SCORE_PARAMETER
        if direct_param:
            score *= FACTOR_DIRECT
        if checked and not (built is not None and facts.sources_in(built[1])):
            score *= FACTOR_VALIDATED_VALUE
            evidence.append(f"validation: value passed through {checked[0]} at line {checked[1]} before use "
                            "(effectiveness not assessed)")
        elif (before := _validation_before(facts, sink_line)) is not None:
            score *= FACTOR_VALIDATION_BEFORE
            evidence.append(f"validation: validation step at line {before} precedes the query "
                            "(effectiveness not assessed)")
        else:
            evidence.append("validation: no validation step before the query")
        carrying = {origin.origin} if origin.kind == "parameter" and origin.origin in facts.data_params else set()
        cand = Candidate(unit_id, score, 0, evidence, carrying)
        if best is None or cand.score > best.score:
            best = cand
    return best


def _source_line(source: Source, facts: _Unit) -> str:
    if source.kind == "external":
        return f"source: external input {source.text} (line {source.line})"
    return f"source: parameter '{source.origin or source.text}' of {facts.qualname}"


# --------------------------------------------------------------------------- paths through callers


def _param_for(callee: _Unit, call: ast.Call, arg_node: ast.AST) -> Optional[str]:
    """Name of the callee parameter that receives `arg_node` in `call`."""
    is_method_call = bool(callee.params) and callee.params[0] in _SELF and isinstance(call.func, ast.Attribute)
    positional = callee.params[1:] if is_method_call else callee.params
    for i, node in enumerate(call.args):
        if node is arg_node:
            return positional[i] if i < len(positional) else None
    for kw in call.keywords:
        if kw.value is arg_node and kw.arg in callee.params:
            return kw.arg
    return None


def _paths(facts_by_id: Mapping[str, _Unit], graph: CodeGraph, current: Dict[str, Candidate], hop: int) -> Dict[str, Candidate]:
    new: Dict[str, Candidate] = {}
    for unit_id, facts in facts_by_id.items():
        for edge in graph.edges_from(unit_id, REL_CALLS):
            callee = current.get(edge.target)
            if callee is None or edge.target == unit_id or not callee.tainted_params:
                continue
            callee_facts = facts_by_id[edge.target]
            for call in (n for n in ast.walk(facts.func) if isinstance(n, ast.Call) and facts.line(n) == edge.line
                         and ast.unparse(n.func) == edge.detail):
                arguments = list(call.args) + [kw.value for kw in call.keywords]
                for arg in arguments:
                    param = _param_for(callee_facts, call, arg)
                    sources = facts.sources_in(arg)
                    if param not in callee.tainted_params or not sources:
                        continue
                    score = callee.score * FACTOR_HOP
                    evidence = [f"path: {facts.qualname} -> {callee_facts.qualname} (call, line {edge.line})"]
                    evidence.append(_source_line(sources[0], facts))
                    if (before := _validation_before(facts, edge.line)) is not None:
                        score *= FACTOR_CALLER_VALIDATES
                        evidence.append(f"validation: validation step at line {before} precedes the call "
                                        "(effectiveness not assessed)")
                    evidence += [l for l in callee.evidence if l.startswith(("path:", "construction:", "sink:", "validation:"))]
                    carrying = {s.origin for s in sources if s.kind == "parameter" and s.origin in facts.data_params}
                    cand = Candidate(unit_id, score, hop, evidence, carrying)
                    if unit_id not in new or cand.score > new[unit_id].score:
                        new[unit_id] = cand
    return new


# --------------------------------------------------------------------------- public API


def scan_sql_candidates(units: Sequence[CodeUnit], graph: CodeGraph) -> List[Candidate]:
    """Candidates for the pattern, best first (score, then unit_id). Failed units are ignored."""
    facts: Dict[str, _Unit] = {}
    for unit in units:
        if unit.parse_status in PARSEABLE and unit.unit_id in graph.nodes:
            try:
                facts[unit.unit_id] = _Unit(unit, graph)
            except (SyntaxError, ValueError):
                continue
    best: Dict[str, Candidate] = {}
    for unit_id, f in facts.items():
        cand = _direct(f, unit_id)
        if cand:
            best[unit_id] = cand
    frontier = dict(best)
    for hop in range(1, MAX_HOPS + 1):
        found = _paths(facts, graph, frontier, hop)
        frontier = {u: c for u, c in found.items() if u not in best or c.score > best[u].score}
        best.update(frontier)
        if not frontier:
            break
    ranked = sorted(best.values(), key=lambda c: (-c.score, c.unit_id))
    for cand in ranked:
        cand.evidence = [f"level: {cand.level} (score {cand.score:.2f})"] + cand.evidence + [DISCLAIMER]
    return ranked


def candidates_to_results(candidates: Sequence[Candidate], query_id: str = "security") -> List[RankedResult]:
    """Candidates as RankedResult records (graph_score = candidate score) so the usual output formats apply."""
    return [RankedResult(query_id=query_id, unit_id=c.unit_id, text_score=0.0, structural_score=0.0,
                         graph_score=c.score, final_score=c.score, evidence=list(c.evidence)) for c in candidates]
