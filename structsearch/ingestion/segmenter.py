"""Split Python source into function-level CodeUnits.

Design decisions
- Units are top-level functions and methods (including methods of nested classes
  and functions defined under if/try/with blocks). Functions nested inside other
  functions are not separate units; they stay part of the parent's source.
- unit_id is '<relative posix path>::<qualname>'. Duplicate qualnames in one file
  (property setters, conditional redefinitions) get '#2', '#3', ... by position.
- start_line includes decorators. Lines are 1-based and match the original file.
- source_text is the exact slice of the file, not dedented. Use parse_unit() to
  get an AST node from it.
- A file that cannot be parsed becomes ONE file-level unit (make_file_unit) with
  parse_status='failed', so it stays searchable by text. It has no AST evidence.
"""
from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath
from typing import List, Tuple

from structsearch.schemas import PARSE_FAILED, PARSE_OK, CodeUnit

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_NEWLINE = re.compile(r"\r\n|\r|\n")


def _collect(node: ast.AST, prefix: str, out: List[Tuple[str, ast.AST]]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNC):
            out.append((prefix + child.name, child))
        elif isinstance(child, ast.ClassDef):
            _collect(child, f"{prefix}{child.name}.", out)
        elif isinstance(child, ast.expr):
            continue  # functions cannot be defined inside expressions
        else:
            _collect(child, prefix, out)


def split_source(source: str, rel_path: str) -> List[CodeUnit]:
    """Return CodeUnits for one file. Raises SyntaxError if the file cannot be parsed."""
    tree = ast.parse(source)
    # Same line model as the Python tokenizer (not str.splitlines, which also
    # splits on form feed and other characters Python does not treat as newlines).
    lines = _NEWLINE.split(source)

    found: List[Tuple[str, ast.AST]] = []
    _collect(tree, "", found)

    spans = []
    for qualname, node in found:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        spans.append((start, node.end_lineno, qualname, node))
    spans.sort(key=lambda s: (s[0], s[1]))

    seen: dict = {}
    units: List[CodeUnit] = []
    for start, end, qualname, node in spans:
        base = f"{rel_path}::{qualname}"
        seen[base] = seen.get(base, 0) + 1
        unit_id = base if seen[base] == 1 else f"{base}#{seen[base]}"
        units.append(
            CodeUnit(
                unit_id=unit_id,
                file_path=rel_path,
                start_line=start,
                end_line=end,
                name=node.name,
                source_text="\n".join(lines[start - 1 : end]),
                language="python",
                parse_status=PARSE_OK,
            )
        )
    return units


def make_file_unit(source: str, rel_path: str) -> CodeUnit:
    """Whole-file unit for a file that could not be parsed (parse_status='failed')."""
    lines = _NEWLINE.split(source)
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()  # trailing newline is not an extra line
    return CodeUnit(
        unit_id=f"{rel_path}::<module>",
        file_path=rel_path,
        start_line=1,
        end_line=len(lines),
        name=PurePosixPath(rel_path).stem,
        source_text="\n".join(lines),
        language="python",
        parse_status=PARSE_FAILED,
    )


def parse_unit(unit: CodeUnit) -> ast.AST:
    """Parse a unit's source and return its FunctionDef/AsyncFunctionDef node.

    Handles indented methods. Line numbers in the returned node are relative to
    the unit (and shifted by one for indented methods).
    """
    try:
        body = ast.parse(unit.source_text).body
    except SyntaxError:
        body = ast.parse("if True:\n" + unit.source_text).body[0].body
    node = body[0]
    if not isinstance(node, _FUNC):
        raise ValueError(f"{unit.unit_id} is not a function definition")
    return node
