"""Code graph records: one node per code unit, typed edges between nodes.

The graph is partial by construction: it holds the explicit calls that can be read from a
function's syntax tree (see builder.py for what is and is not resolved). An edge is something
that was observed in the code, a missing edge is not evidence that no relationship exists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

GRAPH_VERSION = "2"

REL_CALLS = "calls"  # the source calls another unit of the corpus (target: unit_id)
REL_USES_API = "uses_api"  # the source calls a listed API/DB operation (target: marker label)
RELATIONS = (REL_CALLS, REL_USES_API)

# How an edge was found, so that evidence can say what was observed.
METHOD_CALL_NAME = "ast_call_name"  # name(...)
METHOD_CONSTRUCTOR = "ast_constructor_call"  # ClassName(...) resolved to ClassName.__init__
METHOD_SELF_METHOD = "ast_self_method"  # self.name(...) or cls.name(...)
METHOD_CLASS_METHOD = "ast_class_method"  # ClassName.name(...)
METHOD_MARKER = "ast_marker_call"  # a call matching an API/database/validation marker (markers.py)


@dataclass(frozen=True)
class GraphNode:
    unit_id: str
    name: str
    qualname: str
    file_path: str
    parse_status: str


@dataclass(frozen=True)
class GraphEdge:
    source: str  # unit_id
    target: str  # unit_id for `calls`, marker label for `uses_api`
    relation: str
    method: str
    line: int  # 1-based file line of the call site
    detail: str = ""  # the callee as written, e.g. "db.execute" (for evidence text)


@dataclass(frozen=True)
class AmbiguousCall:
    """A call whose name matches several units; no edge is created for it."""

    source: str
    name: str
    candidates: Tuple[str, ...]
    line: int


class CodeGraph:
    def __init__(
        self,
        nodes: Iterable[GraphNode] = (),
        edges: Iterable[GraphEdge] = (),
        ambiguous: Iterable[AmbiguousCall] = (),
    ):
        self.nodes: Dict[str, GraphNode] = {n.unit_id: n for n in nodes}
        self.edges: List[GraphEdge] = sorted(edges, key=lambda e: (e.source, e.line, e.relation, e.target))
        self.ambiguous: List[AmbiguousCall] = list(ambiguous)
        self._out: Dict[str, List[GraphEdge]] = {}
        self._in: Dict[str, List[GraphEdge]] = {}
        for edge in self.edges:
            self._out.setdefault(edge.source, []).append(edge)
            self._in.setdefault(edge.target, []).append(edge)

    # ------------------------------------------------------------------ queries

    def edges_from(self, unit_id: str, relation: Optional[str] = None) -> List[GraphEdge]:
        """Outgoing edges in call-site order."""
        return [e for e in self._out.get(unit_id, ()) if relation in (None, e.relation)]

    def edges_to(self, unit_id: str, relation: Optional[str] = None) -> List[GraphEdge]:
        return [e for e in self._in.get(unit_id, ()) if relation in (None, e.relation)]

    def callees(self, unit_id: str) -> List[str]:
        """Distinct units called by `unit_id`, in order of first call."""
        return list(dict.fromkeys(e.target for e in self.edges_from(unit_id, REL_CALLS)))

    def callers(self, unit_id: str) -> List[str]:
        """Distinct units that call `unit_id`, sorted."""
        return sorted({e.source for e in self.edges_to(unit_id, REL_CALLS)})

    def markers_of(self, unit_id: str) -> List[GraphEdge]:
        """API/database/validation marker edges of a unit in call-site order."""
        return self.edges_from(unit_id, REL_USES_API)

    def units_with_marker(self, label: str) -> List[str]:
        """Units that have at least one marker edge with this label, sorted."""
        return sorted({e.source for e in self.edges if e.relation == REL_USES_API and e.target == label})

    def has_edge(self, source: str, target: str, relation: Optional[str] = None) -> bool:
        return any(e.target == target for e in self.edges_from(source, relation))

    # ------------------------------------------------------------------ persistence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": GRAPH_VERSION,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "ambiguous": [{**asdict(a), "candidates": list(a.candidates)} for a in self.ambiguous],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeGraph":
        return cls(
            (GraphNode(**n) for n in data["nodes"]),
            (GraphEdge(**e) for e in data["edges"]),
            (AmbiguousCall(**{**a, "candidates": tuple(a["candidates"])}) for a in data.get("ambiguous", [])),
        )
