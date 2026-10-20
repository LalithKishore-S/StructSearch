"""AST-derived structural features for one function (Python `ast`, syntax only).

Every feature is a number computed from the unit's own source, including functions
nested inside it. AST evidence describes how code is written, not what it does at
runtime: a self call shows recursion in the code, not that it terminates; an `if` that
raises looks like input validation but is not proof of it.

Definitions
- if_count counts every `if` and `elif`. An `if` that is the only statement in the
  `else` branch of another `if` is treated as `elif` and adds no nesting depth.
- max_depth is the deepest nesting of if/for/while/try/with/match inside the function
  (0 when there are none). max_loop_depth does the same for for/while loops only.
- self_call: a plain function calling its own name; a method calling self.name(...),
  cls.name(...) or ClassName.name(...). super().name(...) is not a self call.
- guard_clause_count: `if` statements directly in the function body whose body ends
  with a raise or return (the usual early-exit validation shape).
- call_in_try_count: calls located in the body of a try statement.
- node_count and the `node:<Type>` histogram skip load/store context markers.
"""
from __future__ import annotations

import ast
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

from structsearch.ingestion.segmenter import parse_unit
from structsearch.schemas import PARSE_FAILED, PARSE_OK, AstRecord, CodeUnit

EXTRACTION_VERSION = "1"
NODE_PREFIX = "node:"

FEATURE_DOC: Dict[str, str] = {
    # control structures
    "if_count": "if and elif statements",
    "for_count": "for loops (including async for)",
    "while_count": "while loops",
    "try_count": "try statements",
    "except_count": "except clauses",
    "finally_count": "try statements with a finally block",
    "with_count": "with statements (including async with)",
    "match_count": "match statements",
    "raise_count": "raise statements",
    "return_count": "return statements",
    "assert_count": "assert statements",
    "yield_count": "yield and yield from expressions",
    "await_count": "await expressions",
    "comprehension_count": "list/set/dict comprehensions and generator expressions",
    "lambda_count": "lambda expressions",
    "nested_def_count": "functions defined inside the function",
    # calls
    "call_count": "call expressions",
    "unique_call_count": "distinct callee names (last name of the callee)",
    "self_call": "1 if the function calls itself (recursion), else 0",
    "self_call_count": "number of self calls",
    "type_check_count": "calls to isinstance or issubclass",
    # structure
    "max_depth": "deepest nesting of control structures",
    "max_loop_depth": "deepest nesting of loops",
    "node_count": "AST nodes in the function",
    "line_count": "source lines of the function",
    "arg_count": "parameters, including *args and **kwargs",
    "decorator_count": "decorators on the function",
    "is_async": "1 for async def",
    "is_generator": "1 if the function yields",
    # selected patterns
    "guard_clause_count": "top-level ifs whose body ends in raise or return",
    "raise_in_if_count": "raise statements located inside an if",
    "call_in_try_count": "calls inside the body of a try",
    "try_with_handler_count": "try statements that have at least one except clause",
    "bare_except_count": "except clauses without an exception type",
}
FEATURE_NAMES: Tuple[str, ...] = tuple(FEATURE_DOC)

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_TRY = tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t is not None)
_MATCH = tuple(t for t in (getattr(ast, "Match", None),) if t is not None)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_CONTROL = (ast.If, ast.With, ast.AsyncWith) + _LOOPS + _TRY + _MATCH
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_TYPE_CHECKS = {"isinstance", "issubclass"}


def _callee_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_self_call(call: ast.Call, fn_name: str, class_name: Optional[str]) -> bool:
    func = call.func
    if class_name is None:  # plain function: a bare call to its own name
        return isinstance(func, ast.Name) and func.id == fn_name
    return (  # method: self.m(), cls.m() or ClassName.m()
        isinstance(func, ast.Attribute)
        and func.attr == fn_name
        and isinstance(func.value, ast.Name)
        and func.value.id in ("self", "cls", class_name)
    )


def _names_from_unit_id(unit: CodeUnit) -> Tuple[str, Optional[str]]:
    qual = unit.unit_id.split("::", 1)[-1].split("#", 1)[0]
    parts = qual.split(".")
    return unit.name, (parts[-2] if len(parts) > 1 else None)


def _ends_with_exit(body: List[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], (ast.Raise, ast.Return))


def extract_from_node(
    root: ast.AST, fn_name: str, class_name: Optional[str], line_count: int
) -> Dict[str, float]:
    """Features for a FunctionDef/AsyncFunctionDef node."""
    count: Counter = Counter()
    hist: Counter = Counter()
    callees = set()
    max_depth = max_loop = 0

    # (node, control depth, loop depth, inside try body, inside if, is an elif)
    stack = [(root, 0, 0, False, False, False)]
    while stack:
        node, depth, loop, in_try, in_if, is_elif = stack.pop()
        if isinstance(node, ast.expr_context):
            continue
        hist[type(node).__name__] += 1
        my_depth, my_loop = depth, loop

        if isinstance(node, _CONTROL):
            my_depth = depth if is_elif else depth + 1
            max_depth = max(max_depth, my_depth)
        if isinstance(node, _LOOPS):
            my_loop = loop + 1
            max_loop = max(max_loop, my_loop)

        if isinstance(node, ast.If):
            count["if_count"] += 1
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            count["for_count"] += 1
        elif isinstance(node, ast.While):
            count["while_count"] += 1
        elif isinstance(node, _TRY):
            count["try_count"] += 1
            count["except_count"] += len(node.handlers)
            if node.handlers:
                count["try_with_handler_count"] += 1
            if node.finalbody:
                count["finally_count"] += 1
            count["bare_except_count"] += sum(1 for h in node.handlers if h.type is None)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            count["with_count"] += 1
        elif _MATCH and isinstance(node, _MATCH):
            count["match_count"] += 1
        elif isinstance(node, ast.Raise):
            count["raise_count"] += 1
            if in_if:
                count["raise_in_if_count"] += 1
        elif isinstance(node, ast.Return):
            count["return_count"] += 1
        elif isinstance(node, ast.Assert):
            count["assert_count"] += 1
        elif isinstance(node, (ast.Yield, ast.YieldFrom)):
            count["yield_count"] += 1
        elif isinstance(node, ast.Await):
            count["await_count"] += 1
        elif isinstance(node, _COMPREHENSIONS):
            count["comprehension_count"] += 1
        elif isinstance(node, ast.Lambda):
            count["lambda_count"] += 1
        elif isinstance(node, _FUNC) and node is not root:
            count["nested_def_count"] += 1
        elif isinstance(node, ast.Call):
            count["call_count"] += 1
            if in_try:
                count["call_in_try_count"] += 1
            name = _callee_name(node)
            if name:
                callees.add(name)
                if name in _TYPE_CHECKS:
                    count["type_check_count"] += 1
            if _is_self_call(node, fn_name, class_name):
                count["self_call_count"] += 1

        # push children, tracking the context they are in
        if isinstance(node, _TRY):
            for child in node.body:
                stack.append((child, my_depth, my_loop, True, in_if, False))
            for child in list(node.handlers) + list(node.orelse) + list(node.finalbody):
                stack.append((child, my_depth, my_loop, in_try, in_if, False))
        elif isinstance(node, ast.If):
            stack.append((node.test, my_depth, my_loop, in_try, True, False))
            for child in node.body:
                stack.append((child, my_depth, my_loop, in_try, True, False))
            orelse = node.orelse
            elif_branch = len(orelse) == 1 and isinstance(orelse[0], ast.If)
            for child in orelse:
                stack.append((child, my_depth, my_loop, in_try, True, elif_branch))
        else:
            for child in ast.iter_child_nodes(node):
                stack.append((child, my_depth, my_loop, in_try, in_if, False))

    body = getattr(root, "body", [])
    args = root.args
    features: Dict[str, float] = {name: float(count.get(name, 0)) for name in FEATURE_NAMES}
    features["unique_call_count"] = float(len(callees))
    features["self_call"] = 1.0 if count["self_call_count"] else 0.0
    features["max_depth"] = float(max_depth)
    features["max_loop_depth"] = float(max_loop)
    features["node_count"] = float(sum(hist.values()))
    features["line_count"] = float(line_count)
    features["arg_count"] = float(
        len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
        + (1 if args.vararg else 0) + (1 if args.kwarg else 0)
    )
    features["decorator_count"] = float(len(root.decorator_list))
    features["is_async"] = 1.0 if isinstance(root, ast.AsyncFunctionDef) else 0.0
    features["is_generator"] = 1.0 if count["yield_count"] else 0.0
    features["guard_clause_count"] = float(
        sum(1 for stmt in body if isinstance(stmt, ast.If) and _ends_with_exit(stmt.body))
    )
    for node_type, n in sorted(hist.items()):
        features[NODE_PREFIX + node_type] = float(n)
    return features


def extract_features(unit: CodeUnit) -> AstRecord:
    """AstRecord for one unit. Units from files that did not parse get no features."""
    if unit.parse_status != PARSE_OK:
        return AstRecord(unit.unit_id, {}, EXTRACTION_VERSION, PARSE_FAILED)
    try:
        node = parse_unit(unit)
    except (SyntaxError, ValueError):
        return AstRecord(unit.unit_id, {}, EXTRACTION_VERSION, PARSE_FAILED)
    fn_name, class_name = _names_from_unit_id(unit)
    line_count = len(unit.source_text.split("\n"))
    features = extract_from_node(node, fn_name, class_name, line_count)
    return AstRecord(unit.unit_id, features, EXTRACTION_VERSION, PARSE_OK)


def extract_all(units: Iterable[CodeUnit]) -> List[AstRecord]:
    return [extract_features(u) for u in units]


def get_feature(record: AstRecord, name: str) -> float:
    """Feature value, 0.0 when absent (node-type counts are stored sparsely)."""
    return record.features.get(name, 0.0)


def node_type_counts(record: AstRecord) -> Dict[str, float]:
    return {k[len(NODE_PREFIX):]: v for k, v in record.features.items() if k.startswith(NODE_PREFIX)}
