"""Error-tolerant segmentation for files Python's parser rejects (Step 9, optional).

Needs `pip install tree-sitter tree-sitter-python` (see requirements-tolerant.txt). Not used unless asked
for (`--tolerant`), and files that parse normally never go through here.

How it works
- tree-sitter parses the broken file and never fails; it marks ERROR / MISSING regions. Those rows are
  reported, and string rows are excluded when looking for `def` lines.
- Functions are found from `def` lines (class context from `class` lines and indentation). Where
  tree-sitter built a clean function node its end line is used, otherwise the end is the last line
  indented deeper than the `def`.
- Each function is then checked with Python's own parser:
    parses              -> parse_status "ok"      (full AST evidence, identical to a normal file)
    parses after repair -> parse_status "partial" (lines with syntax errors skipped; error_lines recorded)
    cannot be repaired  -> parse_status "failed"  (function-level unit, text search only)
Limits: indentation-based ends can be wrong when code inside brackets is dedented; the `def` line itself being
broken (unclosed parentheses in the signature) makes that function "failed".
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from structsearch.ingestion.repair import repair_source
from structsearch.schemas import PARSE_FAILED, PARSE_OK, PARSE_PARTIAL, CodeUnit

_NEWLINE = re.compile(r"\r\n|\r|\n")
_DEF = re.compile(r"^(\s*)(?:async\s+def|def)\s+([A-Za-z_]\w*)")
_CLASS = re.compile(r"^(\s*)class\s+([A-Za-z_]\w*)")
INSTALL_HINT = "pip install tree-sitter tree-sitter-python   (or: pip install -r requirements-tolerant.txt)"


class TolerantUnavailable(RuntimeError):
    """tree-sitter or its Python grammar is not installed."""


_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        try:
            import tree_sitter_python
            from tree_sitter import Language, Parser

            _PARSER = Parser(Language(tree_sitter_python.language()))
        except ImportError as exc:
            raise TolerantUnavailable(f"error-tolerant parsing needs tree-sitter: {INSTALL_HINT}") from exc
        except Exception as exc:  # older tree-sitter API
            raise TolerantUnavailable(f"tree-sitter is installed but too old or incompatible ({exc}); {INSTALL_HINT}") from exc
    return _PARSER


def available() -> bool:
    try:
        _parser()
        return True
    except TolerantUnavailable:
        return False


def _scan_tree(root) -> Tuple[Set[int], Set[int], Dict[int, int]]:
    """(0-based rows with leaf ERROR/MISSING nodes, rows inside multi-line strings, clean def start->end rows)."""
    errors: Set[int] = set()
    in_string: Set[int] = set()
    clean_defs: Dict[int, int] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" and not any(c.type == "ERROR" or c.is_missing for c in node.children):
            errors.add(node.start_point[0])
        if node.is_missing:
            errors.add(node.start_point[0])
        if node.type == "string" and node.end_point[0] > node.start_point[0]:
            in_string.update(range(node.start_point[0] + 1, node.end_point[0] + 1))
        if node.type == "function_definition" and not node.has_error:
            clean_defs[node.start_point[0]] = node.end_point[0] if node.end_point[1] > 0 else node.end_point[0] - 1
        stack.extend(node.children)
    return errors, in_string, clean_defs


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def tolerant_split(source: str, rel_path: str) -> Tuple[List[CodeUnit], List[int]]:
    """Function units of a file that may not parse, plus 1-based lines of its syntax errors."""
    parser = _parser()
    text = _NEWLINE.sub("\n", source)
    lines = text.split("\n")
    tree = parser.parse(text.encode("utf-8", "replace"))
    error_rows, string_rows, clean_defs = _scan_tree(tree.root_node)
    file_errors = sorted(r + 1 for r in error_rows)

    def blank(i: int) -> bool:
        s = lines[i].strip()
        return not s or s.startswith("#")

    units: List[CodeUnit] = []
    seen: Dict[str, int] = {}
    classes: List[Tuple[int, str]] = []
    last_end = -1
    for i, line in enumerate(lines):
        if i in string_rows or blank(i):
            continue
        ind = _indent(line)
        while classes and ind <= classes[-1][0] and not line.lstrip().startswith(("@", ")", "]", "}")):
            classes.pop()
        m = _CLASS.match(line)
        if m:
            classes.append((len(m.group(1)), m.group(2)))
            continue
        m = _DEF.match(line)
        if not m or i <= last_end:
            continue  # not a def, or nested inside the previous function
        n = len(m.group(1))
        end = clean_defs.get(i)
        if end is None:
            end = i
            for j in range(i + 1, len(lines)):
                if j in string_rows:
                    end = j
                elif blank(j):
                    continue
                elif _indent(lines[j]) > n:
                    end = j
                else:
                    break
        start = i
        while start > 0 and lines[start - 1].lstrip().startswith("@") and _indent(lines[start - 1]) == n:
            start -= 1
        last_end = end
        prefix = "".join(f"{name}." for cls_indent, name in classes if cls_indent < n)
        base = f"{rel_path}::{prefix}{m.group(2)}"
        seen[base] = seen.get(base, 0) + 1
        unit_id = base if seen[base] == 1 else f"{base}#{seen[base]}"
        body = "\n".join(lines[start : end + 1])
        status, err_lines = _classify(body, start + 1, {r + 1 for r in error_rows if start <= r <= end})
        units.append(CodeUnit(
            unit_id=unit_id, file_path=rel_path, start_line=start + 1, end_line=end + 1, name=m.group(2),
            source_text=body, language="python", parse_status=status, error_lines=err_lines,
        ))
    return units, file_errors


def _classify(body: str, first_line: int, ts_error_lines: Set[int]) -> Tuple[str, List[int]]:
    from structsearch.ingestion.repair import _error_line

    node, _ = _error_line(body)
    if node is not None:
        return PARSE_OK, []
    repaired = repair_source(body)
    if repaired is None:
        return PARSE_FAILED, sorted(ts_error_lines)
    edited = {first_line + n - 1 for n in repaired[1]}
    return PARSE_PARTIAL, sorted(edited | ts_error_lines)


def file_unit_name(rel_path: str) -> str:
    return PurePosixPath(rel_path).stem
