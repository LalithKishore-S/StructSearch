"""Tree fragments: a bag of *structural relations* between the parts of a function.

Feature counts (features.py) say what a function contains. Fragments say how the parts are
arranged, so "a try inside a loop" and "a try next to a loop" become different.

The function's syntax tree is first reduced to a *skeleton*: only statements and
expressions that matter structurally are kept (If, For, Try, Call, BinOp, ...); names,
constants, operators and context nodes are transparent. Each kept node carries labels:

  base label      the node kind, e.g. If, For, Try, With, Call, BinOp
                  (async variants are folded in: AsyncFor -> For, AsyncWith -> With)
  specific labels Call:open  Call:os.system  BinOp:Add  ExceptHandler:bare
                  ExceptHandler:ValueError  Raise:ValueError  UnaryOp:Not

Fragment terms (strings, one per relation; the prefix says which relation):

  u:A            the function has a node labelled A (count = how many)
  pc:A>B         a node labelled A has a B as its nearest kept child (count)
  ch3:A>B>C      a three-node chain of base labels (count)
  ad:A//B        an A contains a B somewhere below it (presence)
  ord:A=>B       an A ends before a B starts, and A does not contain B (presence);
                 only for labels that matter for ordering (see ORD_BASES)

Used two ways: pattern constraints test single terms ("ad:With//Call:open" present?),
and query-by-example ranks functions by BM25 over all terms of a pasted snippet.
"""
from __future__ import annotations

import ast
import textwrap
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from structsearch.ingestion.segmenter import parse_unit
from structsearch.schemas import PARSE_FAILED, PARSE_OK, PARSEABLE, CodeUnit

FRAGMENT_VERSION = "1"
MAX_ORD_NODES = 300  # ordering pairs are quadratic; very large functions only get their first nodes

# ast class name -> base label. Everything not listed is transparent.
_BASE: Dict[str, str] = {
    "FunctionDef": "FunctionDef", "AsyncFunctionDef": "FunctionDef", "ClassDef": "ClassDef", "Lambda": "Lambda",
    "If": "If", "For": "For", "AsyncFor": "For", "While": "While",
    "Try": "Try", "TryStar": "Try", "ExceptHandler": "ExceptHandler",
    "With": "With", "AsyncWith": "With", "Match": "Match",
    "Return": "Return", "Raise": "Raise", "Assert": "Assert", "Delete": "Delete",
    "Assign": "Assign", "AugAssign": "AugAssign", "AnnAssign": "AnnAssign",
    "Import": "Import", "ImportFrom": "Import", "Pass": "Pass", "Break": "Break", "Continue": "Continue",
    "Call": "Call", "BinOp": "BinOp", "BoolOp": "BoolOp", "UnaryOp": "UnaryOp", "Compare": "Compare",
    "IfExp": "IfExp", "Subscript": "Subscript", "JoinedStr": "JoinedStr", "Await": "Await",
    "Yield": "Yield", "YieldFrom": "Yield",
    "ListComp": "Comprehension", "SetComp": "Comprehension", "DictComp": "Comprehension",
    "GeneratorExp": "Comprehension",
}
BASE_LABELS: Tuple[str, ...] = tuple(sorted(set(_BASE.values())))
_CANONICAL = {name.lower(): name for name in BASE_LABELS}

# Bases that may carry a ":specific" suffix, and bases usable on either side of "=>".
SPECIFIC_BASES = ("Call", "BinOp", "UnaryOp", "ExceptHandler", "Raise")
ORD_BASES = frozenset(
    {"If", "For", "While", "Try", "ExceptHandler", "With", "Raise", "Assert", "Return", "Call",
     "Await", "Yield", "BinOp", "JoinedStr", "Delete", "Import"}
)
BINOP_NAMES = ("Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow", "LShift", "RShift",
               "BitOr", "BitXor", "BitAnd", "MatMult")
_BINOP_LOOKUP = {n.lower(): n for n in BINOP_NAMES}
_UNARY_LOOKUP = {n.lower(): n for n in ("Not", "USub", "UAdd", "Invert")}

TERM_KINDS = ("u", "pc", "ch3", "ad", "ord")


def canonical_base(name: str) -> Optional[str]:
    return _CANONICAL.get(name.lower())


def canonical_specific(base: str, spec: str) -> Optional[str]:
    """Normalise the part after ':' (None if it is not valid for that base label)."""
    if base == "BinOp":
        return _BINOP_LOOKUP.get(spec.lower())
    if base == "UnaryOp":
        return _UNARY_LOOKUP.get(spec.lower())
    if base in ("Call", "ExceptHandler", "Raise"):
        ok = bool(spec) and all(part.isidentifier() for part in spec.split("."))
        return spec if ok else None
    return None


# --------------------------------------------------------------------------- labels


def _dotted(node: ast.AST) -> Optional[str]:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _exception_names(node: Optional[ast.AST]) -> List[str]:
    if node is None:
        return ["bare"]
    if isinstance(node, ast.Tuple):
        return [n for elt in node.elts for n in _exception_names(elt)]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    return []


def node_labels(node: ast.AST) -> List[str]:
    """Labels of a kept node (base label first), or [] if the node is transparent."""
    base = _BASE.get(type(node).__name__)
    if base is None:
        return []
    labels = [base]
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            labels.append(f"Call:{func.id}")
        elif isinstance(func, ast.Attribute):
            labels.append(f"Call:{func.attr}")
            dotted = _dotted(func)
            if dotted and dotted.count(".") <= 2 and dotted.split(".")[0] not in ("self", "cls"):
                labels.append(f"Call:{dotted}")
    elif isinstance(node, ast.BinOp):
        labels.append(f"BinOp:{type(node.op).__name__}")
    elif isinstance(node, ast.UnaryOp):
        labels.append(f"UnaryOp:{type(node.op).__name__}")
    elif isinstance(node, ast.ExceptHandler):
        labels.extend(f"ExceptHandler:{n}" for n in _exception_names(node.type))
    elif isinstance(node, ast.Raise) and node.exc is not None:
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        labels.extend(f"Raise:{n}" for n in _exception_names(exc) if n != "bare")
    return list(dict.fromkeys(labels))


# --------------------------------------------------------------------------- extraction


def fragment_terms(root: ast.AST) -> Dict[str, int]:
    """Fragment terms of a function (or snippet) rooted at `root`. The root itself is not labelled."""
    nodes: List[Tuple[List[str], int]] = []  # (labels, parent index) in preorder
    stack: List[Tuple[ast.AST, int]] = [(child, -1) for child in reversed(list(ast.iter_child_nodes(root)))]
    while stack:
        node, parent = stack.pop()
        labels = node_labels(node)
        index = parent
        if labels:
            index = len(nodes)
            nodes.append((labels, parent))
        stack.extend((child, index) for child in reversed(list(ast.iter_child_nodes(node))))

    terms: Counter = Counter()
    ancestors: List[List[int]] = []
    for i, (labels, parent) in enumerate(nodes):
        chain = ancestors[parent] + [parent] if parent >= 0 else []
        ancestors.append(chain)
        for label in labels:
            terms[f"u:{label}"] += 1
        if parent >= 0:
            for parent_label in nodes[parent][0]:
                for label in labels:
                    terms[f"pc:{parent_label}>{label}"] += 1
            grand = nodes[parent][1]
            if grand >= 0:
                terms[f"ch3:{nodes[grand][0][0]}>{nodes[parent][0][0]}>{labels[0]}"] += 1
        for a in chain:
            for anc_label in nodes[a][0]:
                for label in labels:
                    terms[f"ad:{anc_label}//{label}"] = 1

    # ord: A ends before B starts. Subtree of i is the preorder range [i, end[i]).
    size = [1] * len(nodes)
    for i in range(len(nodes) - 1, -1, -1):
        parent = nodes[i][1]
        if parent >= 0:
            size[parent] += size[i]
    ordered = [i for i, (labels, _) in enumerate(nodes) if labels[0] in ORD_BASES][:MAX_ORD_NODES]
    for pos, i in enumerate(ordered):
        end = i + size[i]
        for j in ordered[pos + 1:]:
            if j >= end:
                for a_label in nodes[i][0]:
                    for b_label in nodes[j][0]:
                        terms[f"ord:{a_label}=>{b_label}"] = 1
    return dict(terms)


class FragmentRecord:
    """Fragment terms of one unit (empty for units whose file did not parse)."""

    def __init__(self, unit_id: str, terms: Dict[str, int], extraction_version: str = FRAGMENT_VERSION,
                 parse_status: str = PARSE_OK):
        self.unit_id = unit_id
        self.terms = terms
        self.extraction_version = extraction_version
        self.parse_status = parse_status

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FragmentRecord) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        return f"FragmentRecord({self.unit_id!r}, {len(self.terms)} terms, {self.parse_status})"

    def to_dict(self) -> Dict[str, object]:
        return {"unit_id": self.unit_id, "terms": self.terms,
                "extraction_version": self.extraction_version, "parse_status": self.parse_status}

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FragmentRecord":
        return cls(str(data["unit_id"]), {str(k): int(v) for k, v in dict(data["terms"]).items()},  # type: ignore[arg-type]
                   str(data.get("extraction_version", FRAGMENT_VERSION)), str(data.get("parse_status", PARSE_OK)))


def extract_fragments(unit: CodeUnit) -> FragmentRecord:
    if unit.parse_status not in PARSEABLE:
        return FragmentRecord(unit.unit_id, {}, FRAGMENT_VERSION, PARSE_FAILED)
    try:
        node = parse_unit(unit)
    except (SyntaxError, ValueError, RecursionError):
        return FragmentRecord(unit.unit_id, {}, FRAGMENT_VERSION, PARSE_FAILED)
    return FragmentRecord(unit.unit_id, fragment_terms(node), FRAGMENT_VERSION, unit.parse_status)


def extract_all_fragments(units: Iterable[CodeUnit]) -> List[FragmentRecord]:
    return [extract_fragments(u) for u in units]


def snippet_terms(code: str) -> Dict[str, int]:
    """Fragment terms of a pasted snippet: a whole function, or loose statements (wrapped if needed).

    Raises ValueError when the snippet is not valid Python.
    """
    source = textwrap.dedent(code).strip("\n")
    if not source.strip():
        raise ValueError("the snippet is empty")
    try:
        tree: ast.AST = ast.parse(source)
    except SyntaxError:
        body = "\n".join("    " + line for line in source.split("\n"))
        try:
            tree = ast.parse("def _snippet():\n" + body)
        except SyntaxError as exc:
            raise ValueError(f"the snippet is not valid Python: {exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("the snippet is too deeply nested") from exc
    body_nodes = getattr(tree, "body", [])
    if len(body_nodes) == 1 and isinstance(body_nodes[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        tree = body_nodes[0]  # a single function: its own name/decorators are not part of the shape
    return fragment_terms(tree)


def split_term(term: str) -> Tuple[str, str]:
    kind, _, rest = term.partition(":")
    return kind, rest


def describe_term(term: str) -> str:
    """Readable form of a term, e.g. 'ad:For//Try' -> 'For contains Try'."""
    kind, rest = split_term(term)
    if kind == "u":
        return f"has {rest}"
    if kind == "pc":
        return rest.replace(">", " has child ", 1) if rest.count(">") == 1 else rest
    if kind == "ch3":
        return rest.replace(">", " > ")
    if kind == "ad":
        return rest.replace("//", " contains ")
    if kind == "ord":
        return rest.replace("=>", " before ")
    return term
