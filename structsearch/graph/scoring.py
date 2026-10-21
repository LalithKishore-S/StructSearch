"""Graph scoring: relationship-style queries over the call graph and its markers.

A query is mapped (by rules) to relationships the graph can express; each unit gets a score in
(0, 1] per relationship, scores of several relationships are averaged, and every positive score
comes with factual evidence lines. The result plugs into fusion as `graph_scores` / `graph_evidence`
(see retrieval/fusion.py). Units that do not satisfy the relationship are left out (score 0).

Relationships (INTENT_DOC) and scores
  validated_db     a validation step before database access in the same unit
                       1.0 validation step strictly before the access (earlier line)
                       0.4 validation step present but not before it (later or same line)
                       0.25 database access with no validation step
                   all multiplied by DECAY[depth] (see below)
  unvalidated_db   database access with no validation step before it: DECAY[depth], else absent
  db_access        database access: DECAY[depth]
  calls_validator  at least one validation step: 1.0
  file_access      a file:open marker: DECAY[depth]
  recursive        a call to itself 1.0; part of a call cycle of at most 4 calls 0.8

Definitions
  database access  a `db:execute` marker in the unit itself (depth 0) or in a function it calls,
                   reached through at most 3 `calls` edges (depth 1..3); DECAY = 1.0, 0.7, 0.5, 0.35.
                   For a callee, the call-site line in the calling unit is the access position.
  validation step  a `validation:validate` marker in the unit (a call named like validation), or,
                   when AST records are given, a call to a corpus function that has guard clauses
                   that raise (an `if` that ends in `raise` directly in its body).
  before           a strictly smaller line number inside the same unit. For access through callees the
                   whole call chain counts: a validation step in the caller before the call, or in a
                   callee before its own access or next call, makes the access validated. Lines give the order of
                   call sites in the source, not an execution order: branches, loops and early
                   returns are not modelled and nothing says the validated value is the one used.

Scores say how well the observed edges fit the relationship; they are not proof of behaviour.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from structsearch.graph.model import REL_CALLS, CodeGraph, GraphEdge
from structsearch.schemas import PARSEABLE, AstRecord

INTENTS = ("validated_db", "unvalidated_db", "db_access", "calls_validator", "file_access", "recursive")

INTENT_DOC: Dict[str, str] = {
    "validated_db": "a validation step before database access",
    "unvalidated_db": "database access with no validation step before it (candidate for review)",
    "db_access": "database access (a db:execute marker, directly or in a called function)",
    "calls_validator": "calls something named like a validation step",
    "file_access": "opens a file (a file:open marker, directly or in a called function)",
    "recursive": "calls itself, or is part of a short call cycle",
}

DECAY: Dict[int, float] = {0: 1.0, 1: 0.7, 2: 0.5, 3: 0.35}
MAX_DEPTH = 3
MAX_CYCLE = 4
FACTOR_VALIDATED, FACTOR_VALIDATION_ELSEWHERE, FACTOR_NO_VALIDATION = 1.0, 0.4, 0.25
SCORE_MUTUAL_RECURSION = 0.8

DB_LABEL = "db:execute"
FILE_LABEL = "file:open"
VALIDATION_LABEL = "validation:validate"

# --------------------------------------------------------------------------- query -> intents

_WORDS = re.compile(r"[a-z]+")
_VALIDATION_STEMS = ("valid", "sanitiz", "sanitis", "verif", "check", "escap")
_DB_WORDS = {"database", "databases", "db", "sql", "sqlite", "query", "queries", "execute", "executes", "cursor"}
_FILE_WORDS = {"file", "files", "open", "opens", "opened", "opening"}
_NEGATION = {"without", "missing", "unvalidated", "unsanitized", "unsanitised", "unsafe", "unchecked", "lacking",
             "lacks", "no", "not", "never", "skips", "bypass", "weak"}
_IMPLIES_NO_VALIDATION = {"unvalidated", "unsanitized", "unsanitised", "unchecked", "unsafe"}


def graph_intents(query: str) -> List[str]:
    """Relationships (in INTENTS order) a query asks for; empty if it asks for none the graph can express."""
    words = _WORDS.findall(query.lower())
    has_validation = any(w.startswith(_VALIDATION_STEMS) for w in words)
    has_db = any(w in _DB_WORDS for w in words)
    has_file = any(w in _FILE_WORDS for w in words)
    negated = any(w in _NEGATION for w in words)
    no_validation_word = any(w in _IMPLIES_NO_VALIDATION for w in words)
    injection = any(w.startswith("inject") for w in words)
    found = set()
    if has_db and (injection or (negated and (has_validation or no_validation_word))):
        found.add("unvalidated_db")
    elif has_db and has_validation:
        found.add("validated_db")
    elif has_db:
        found.add("db_access")
    elif has_validation:
        found.add("calls_validator")
    if has_file:
        found.add("file_access")
    if any(w.startswith("recurs") or w == "itself" for w in words):
        found.add("recursive")
    return [i for i in INTENTS if i in found]


# --------------------------------------------------------------------------- result


@dataclass
class GraphResult:
    scores: Dict[str, float] = field(default_factory=dict)  # unit_id -> score in (0, 1]; absent = 0
    evidence: Dict[str, List[str]] = field(default_factory=dict)  # unit_id -> factual lines
    intents: List[str] = field(default_factory=list)


@dataclass
class _Site:
    """A position in a unit where a marked operation happens, directly or through callees."""

    line: int  # line of the marker (depth 0) or of the first call towards it (depth > 0)
    depth: int
    path: List[GraphEdge]  # call edges from the unit down to the owner
    marker: GraphEdge
    owner: str  # unit that holds the marker


@dataclass
class _Step:
    line: int
    edge: Optional[GraphEdge] = None  # call edge at that line (to a corpus validator)
    marker: Optional[GraphEdge] = None
    structural: Optional[str] = None  # unit_id of a callee recognised by its guard clauses


class _Scorer:
    def __init__(self, graph: CodeGraph, ast_records: Optional[Sequence[AstRecord]] = None):
        self.graph = graph
        self.validators = self._structural_validators(ast_records)
        self._reach: Dict[str, Dict[str, _Site]] = {}

    # ---- helpers

    @staticmethod
    def _structural_validators(records: Optional[Sequence[AstRecord]]) -> set:
        out = set()
        for rec in records or ():
            f = rec.features
            if rec.parse_status in PARSEABLE and f.get("guard_clause_count", 0) >= 1 and f.get("raise_count", 0) >= 1:
                out.add(rec.unit_id)
        return out

    def name(self, unit_id: str) -> str:
        node = self.graph.nodes.get(unit_id)
        return node.qualname if node else unit_id

    def edge_line(self, edge: GraphEdge) -> str:
        return f"edge: {self.name(edge.source)} -> {self.name(edge.target)} (call, line {edge.line})"

    def marker_line(self, edge: GraphEdge, owner: Optional[str] = None) -> str:
        where = f" in {self.name(owner)}" if owner else ""
        return f"marker: {edge.target} at line {edge.line}{where} ({edge.detail})"

    # ---- sites (database / file access)

    def reach(self, label: str) -> Dict[str, _Site]:
        """Best site per unit: its own marker, else through the callee with the smallest depth."""
        if label in self._reach:
            return self._reach[label]
        best: Dict[str, _Site] = {}
        for unit_id in self.graph.nodes:
            direct = [e for e in self.graph.markers_of(unit_id) if e.target == label]
            if direct:
                first = min(direct, key=lambda e: e.line)
                best[unit_id] = _Site(first.line, 0, [], first, unit_id)
        for depth in range(1, MAX_DEPTH + 1):
            layer: Dict[str, _Site] = {}
            for unit_id in self.graph.nodes:
                if unit_id in best:
                    continue
                for edge in self.graph.edges_from(unit_id, REL_CALLS):
                    callee = best.get(edge.target)
                    if edge.target != unit_id and callee is not None and callee.depth == depth - 1:
                        layer[unit_id] = _Site(edge.line, depth, [edge] + callee.path, callee.marker, callee.owner)
                        break
            best.update(layer)
        self._reach[label] = best
        return best

    def sites(self, unit_id: str, label: str) -> List[_Site]:
        reach = self.reach(label)
        found = [_Site(e.line, 0, [], e, unit_id) for e in self.graph.markers_of(unit_id) if e.target == label]
        for edge in self.graph.edges_from(unit_id, REL_CALLS):
            callee = reach.get(edge.target)
            if edge.target != unit_id and callee is not None and callee.depth + 1 <= MAX_DEPTH:
                found.append(_Site(edge.line, callee.depth + 1, [edge] + callee.path, callee.marker, callee.owner))
        return sorted(found, key=lambda s: (s.depth, s.line))

    def site_evidence(self, site: _Site) -> List[str]:
        lines = [self.edge_line(e) for e in site.path]
        lines.append(self.marker_line(site.marker, site.owner if site.depth else None))
        return lines

    # ---- validation steps

    def steps(self, unit_id: str) -> List[_Step]:
        by_line: Dict[int, _Step] = {}
        calls = self.graph.edges_from(unit_id, REL_CALLS)
        for marker in self.graph.markers_of(unit_id):
            if marker.target != VALIDATION_LABEL:
                continue
            step = by_line.setdefault(marker.line, _Step(marker.line))
            step.marker = step.marker or marker
            step.edge = next((e for e in calls if e.line == marker.line and e.detail == marker.detail), None)
        for edge in calls:
            if edge.target in self.validators and edge.target != unit_id:
                step = by_line.setdefault(edge.line, _Step(edge.line))
                step.edge = step.edge or edge
                step.structural = edge.target
        return [by_line[line] for line in sorted(by_line)]

    def step_evidence(self, step: _Step) -> List[str]:
        lines = []
        if step.edge is not None:
            lines.append(self.edge_line(step.edge))
        if step.marker is not None:
            lines.append(self.marker_line(step.marker))
        if step.structural is not None:
            lines.append(f"structure: {self.name(step.structural)} has guard clauses that raise (AST)")
        return lines

    def chain_validation(self, site: _Site, unit_id: str) -> Optional[Tuple[str, int]]:
        """First validation step before the access along the call chain: (unit_id, line), nearest the start first.

        The chain is this unit up to its first call towards the access, then each callee up to its own next
        call, and finally the unit that holds the marker up to the marker."""
        positions = [(edge.source, edge.line) for edge in site.path] + [(site.owner, site.marker.line)]
        if not site.path:
            positions = [(unit_id, site.line)]
        for owner, line in positions:
            before = [s for s in self.steps(owner) if s.line < line]
            if before:
                return owner, before[0].line
        return None

    # ---- relationships

    def validated_db(self, unit_id: str) -> Tuple[float, List[str]]:
        sites, steps = self.sites(unit_id, DB_LABEL), self.steps(unit_id)
        best: Optional[Tuple[float, int, int, _Site, float]] = None
        for site in sites:
            if self.chain_validation(site, unit_id) is not None:
                factor = FACTOR_VALIDATED
            elif steps:
                factor = FACTOR_VALIDATION_ELSEWHERE
            else:
                factor = FACTOR_NO_VALIDATION
            value = DECAY[site.depth] * factor
            if best is None or (value, -site.depth, -site.line) > best[:3]:
                best = (value, -site.depth, -site.line, site, factor)
        if best is None:
            return 0.0, []
        value, _, _, site, factor = best
        evidence: List[str] = []
        chain = self.chain_validation(site, unit_id) if factor == FACTOR_VALIDATED else None
        if steps and (chain is None or chain[0] == unit_id):
            evidence += self.step_evidence(steps[0])
        evidence += self.site_evidence(site)
        if chain is not None and chain[0] == unit_id:
            evidence.append(f"order: validation (line {chain[1]}) is before database access (line {site.line})")
        elif chain is not None:
            evidence.append(f"order: validation in {self.name(chain[0])} (line {chain[1]}) is before database access "
                            f"(line {site.marker.line})")
        elif factor == FACTOR_VALIDATION_ELSEWHERE:
            evidence.append(
                f"order: validation (line {steps[0].line}) is not before database access (line {site.line})")
        else:
            evidence.append(f"order: no validation step in {self.name(unit_id)}")
        return value, evidence

    def unvalidated_db(self, unit_id: str) -> Tuple[float, List[str]]:
        open_sites = [s for s in self.sites(unit_id, DB_LABEL) if self.chain_validation(s, unit_id) is None]
        if not open_sites:
            return 0.0, []
        site = open_sites[0]  # sites are sorted by depth, then line
        evidence = self.site_evidence(site)
        evidence.append(f"order: no validation step before database access (line {site.line})")
        return DECAY[site.depth], evidence

    def db_access(self, unit_id: str) -> Tuple[float, List[str]]:
        sites = self.sites(unit_id, DB_LABEL)
        return (DECAY[sites[0].depth], self.site_evidence(sites[0])) if sites else (0.0, [])

    def file_access(self, unit_id: str) -> Tuple[float, List[str]]:
        sites = self.sites(unit_id, FILE_LABEL)
        return (DECAY[sites[0].depth], self.site_evidence(sites[0])) if sites else (0.0, [])

    def calls_validator(self, unit_id: str) -> Tuple[float, List[str]]:
        steps = self.steps(unit_id)
        return (1.0, self.step_evidence(steps[0])) if steps else (0.0, [])

    def recursive(self, unit_id: str) -> Tuple[float, List[str]]:
        calls = self.graph.edges_from(unit_id, REL_CALLS)
        own = [e for e in calls if e.target == unit_id]
        if own:
            return 1.0, [self.edge_line(e) for e in own]
        frontier: List[Tuple[str, List[GraphEdge]]] = [(unit_id, [])]
        seen = {unit_id}
        for _ in range(MAX_CYCLE):
            nxt: List[Tuple[str, List[GraphEdge]]] = []
            for node, path in frontier:
                for edge in self.graph.edges_from(node, REL_CALLS):
                    if edge.target == unit_id:
                        return SCORE_MUTUAL_RECURSION, [self.edge_line(e) for e in path + [edge]]
                    if edge.target not in seen:
                        seen.add(edge.target)
                        nxt.append((edge.target, path + [edge]))
            frontier = nxt
        return 0.0, []


def score_graph(
    graph: CodeGraph,
    query: Optional[str] = None,
    intents: Optional[Sequence[str]] = None,
    ast_records: Optional[Sequence[AstRecord]] = None,
) -> GraphResult:
    """Score every unit for the relationships of `query` (or the explicit `intents`).

    Several relationships are averaged. With no relationship the result is empty, which fusion
    treats as "no graph signal for this query".
    """
    if intents is None:
        if query is None:
            raise ValueError("give a query or explicit intents")
        chosen = graph_intents(query)
    else:
        unknown = [i for i in intents if i not in INTENTS]
        if unknown:
            raise ValueError(f"unknown graph intent(s): {', '.join(unknown)} (known: {', '.join(INTENTS)})")
        chosen = [i for i in INTENTS if i in intents]
    result = GraphResult(intents=chosen)
    if not chosen:
        return result
    scorer = _Scorer(graph, ast_records)
    for unit_id in graph.nodes:
        total, evidence = 0.0, []
        for intent in chosen:
            value, lines = getattr(scorer, intent)(unit_id)
            if value > 0:
                total += value
                evidence += [line for line in lines if line not in evidence]
        if total > 0:
            result.scores[unit_id] = total / len(chosen)
            result.evidence[unit_id] = evidence
    return result
