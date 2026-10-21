"""Build the call graph of a corpus from its code units (Python `ast`, explicit calls only).

What becomes an edge (relation `calls`, source -> target are unit_ids):
  name(...)             a function of the corpus with that name. A function in the same file wins;
                        otherwise the name must belong to exactly one unit of the corpus.
  ClassName(...)        the `ClassName.__init__` unit, resolved the same way.
  self.name(...)        the method `name` of the same class (also cls.name(...)).
  ClassName.name(...)   the method `name` of a class defined in the same file.
Calls are attributed to the unit they are written in, including calls inside nested functions and
lambdas of that unit; decorators and default values are not part of the unit's body. Every call
site is its own edge (with its line), so call order is available to scoring.

What is NOT modelled (graph evidence is partial):
  - obj.method(...) on any other object, super().method(...), inherited methods;
  - aliases and rebinding (`g = f; g()`, `import x as y`), dynamic dispatch, callbacks passed as
    arguments, getattr/eval, decorators that change what is called;
  - calls into the standard library or other packages, except the listed API/database/validation
    operations of markers.py, which become `uses_api` edges (target: marker label);
  - names that are ambiguous (several candidates): no edge, the call is listed in `graph.ambiguous`;
  - a name that is a parameter or is assigned inside the function is treated as a local, not a call
    to the corpus function of the same name (variables of a comprehension stay inside it).
Units that did not parse get a node and no edges and are never an edge target; partial units
(tolerant parsing) contribute the calls of their surviving lines.
"""
from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Set, Tuple

from structsearch.graph.markers import DEFAULT_MARKERS, Marker, match_markers
from structsearch.graph.model import (
    METHOD_CALL_NAME,
    METHOD_CLASS_METHOD,
    METHOD_CONSTRUCTOR,
    METHOD_MARKER,
    METHOD_SELF_METHOD,
    REL_CALLS,
    REL_USES_API,
    AmbiguousCall,
    CodeGraph,
    GraphEdge,
    GraphNode,
)
from structsearch.ingestion.segmenter import parse_unit
from structsearch.schemas import PARSEABLE, CodeUnit

_SELF_NAMES = ("self", "cls")
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def qualname_of(unit: CodeUnit) -> str:
    """'Class.method' or 'function' (the part of the unit_id after '::', without a #n suffix)."""
    return unit.unit_id.split("::", 1)[-1].split("#", 1)[0]


class _Index:
    """Lookup tables over the parseable units of a corpus."""

    def __init__(self, units: Sequence[CodeUnit]):
        self.functions: Dict[str, List[CodeUnit]] = {}  # plain function name -> units
        self.constructors: Dict[str, List[CodeUnit]] = {}  # class name -> its __init__ units
        self.methods: Dict[Tuple[str, str], List[CodeUnit]] = {}  # (file, 'Class.method') -> units
        for unit in units:
            if unit.parse_status not in PARSEABLE:
                continue
            qual = qualname_of(unit)
            parts = qual.split(".")
            if len(parts) == 1:
                self.functions.setdefault(unit.name, []).append(unit)
            else:
                self.methods.setdefault((unit.file_path, qual), []).append(unit)
                if len(parts) == 2 and parts[1] == "__init__":
                    self.constructors.setdefault(parts[0], []).append(unit)


def _local_names(func: ast.AST) -> Set[str]:
    names: Set[str] = set()
    args = func.args  # type: ignore[attr-defined]
    for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.add(arg.arg)
    for arg in (args.vararg, args.kwarg):
        if arg is not None:
            names.add(arg.arg)
    scoped = {id(n) for c in ast.walk(func) if isinstance(c, _COMPREHENSIONS)
              for g in c.generators for n in ast.walk(g.target)}  # comprehension variables do not leak out
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and id(node) not in scoped:
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not func:
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def _body_calls(func: ast.AST) -> List[ast.Call]:
    calls = [n for stmt in func.body for n in ast.walk(stmt) if isinstance(n, ast.Call)]  # type: ignore[attr-defined]
    return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


def _pick(candidates: List[CodeUnit], file_path: str) -> Tuple[Optional[CodeUnit], List[CodeUnit]]:
    """(chosen, candidates considered): same-file candidates win; exactly one must remain."""
    same_file = [c for c in candidates if c.file_path == file_path]
    pool = same_file or candidates
    return (pool[0] if len(pool) == 1 else None), pool


def _unit_edges(
    unit: CodeUnit, index: _Index, markers: Sequence[Marker]
) -> Tuple[List[GraphEdge], List[AmbiguousCall]]:
    try:
        func = parse_unit(unit)
    except (SyntaxError, ValueError):
        return [], []
    first = min([func.lineno] + [d.lineno for d in func.decorator_list])  # type: ignore[attr-defined]
    local = _local_names(func)
    qual = qualname_of(unit)
    class_qual = qual.rsplit(".", 1)[0] if "." in qual else None
    edges: List[GraphEdge] = []
    ambiguous: List[AmbiguousCall] = []

    def link(call: ast.Call, candidates: List[CodeUnit], method: str) -> bool:
        """Add the call edge if the target is unique; True when the call was resolved."""
        chosen, pool = _pick(candidates, unit.file_path)
        line = unit.start_line + (call.lineno - first)
        if chosen is not None:
            edges.append(GraphEdge(unit.unit_id, chosen.unit_id, REL_CALLS, method, line, ast.unparse(call.func)))
            return True
        if len(pool) > 1:
            ambiguous.append(AmbiguousCall(unit.unit_id, ast.unparse(call.func), tuple(sorted(c.unit_id for c in pool)), line))
        return False

    for call in _body_calls(func):
        resolved = _resolve(call, unit, index, local, class_qual, link)
        line = unit.start_line + (call.lineno - first)
        for marker, detail in match_markers(call, local, markers):
            if marker.category == "validation" or not resolved:
                edges.append(GraphEdge(unit.unit_id, marker.label, REL_USES_API, METHOD_MARKER, line, detail))
    return edges, ambiguous


def _resolve(call, unit, index, local, class_qual, link) -> bool:
    """Try to resolve one call to a unit of the corpus; True if an edge was added."""
    callee = call.func
    if isinstance(callee, ast.Name) and callee.id not in local:
        if callee.id in index.functions:
            return link(call, index.functions[callee.id], METHOD_CALL_NAME)
        if callee.id in index.constructors:
            return link(call, index.constructors[callee.id], METHOD_CONSTRUCTOR)
    elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
        owner = callee.value.id
        if owner in _SELF_NAMES and class_qual:
            found = index.methods.get((unit.file_path, f"{class_qual}.{callee.attr}"), [])
            return bool(found) and link(call, found, METHOD_SELF_METHOD)
        if owner not in local:
            found = index.methods.get((unit.file_path, f"{owner}.{callee.attr}"), [])
            return bool(found) and link(call, found, METHOD_CLASS_METHOD)
    return False


def build_graph(units: Sequence[CodeUnit], markers: Sequence[Marker] = DEFAULT_MARKERS) -> CodeGraph:
    """Nodes for every unit, `calls` edges for the explicit calls described in the module docstring and
    `uses_api` edges for calls matching `markers` (see markers.py)."""
    index = _Index(units)
    nodes = [
        GraphNode(u.unit_id, u.name, qualname_of(u), u.file_path, u.parse_status) for u in units
    ]
    edges: List[GraphEdge] = []
    ambiguous: List[AmbiguousCall] = []
    for unit in units:
        if unit.parse_status not in PARSEABLE:
            continue
        found, unclear = _unit_edges(unit, index, markers)
        edges.extend(found)
        ambiguous.extend(unclear)
    return CodeGraph(nodes, edges, ambiguous)
