"""Best-effort repair of a function's source so Python's own parser can read the rest of it.

Used for units cut out of files that do not parse (Step 9). The edit is deterministic: while ast
reports a syntax error, the offending line is replaced by `pass` (same indentation); if the same
line fails again it is blanked. Nothing is invented: only lines are removed, so every structural
fact found in the repaired text is really in the original. If the repair cannot reach a valid
function, the caller treats the unit as unparsed.
"""
from __future__ import annotations

import ast
from typing import List, Optional, Tuple

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def _error_line(text: str) -> Tuple[Optional[ast.AST], Optional[int]]:
    """(function node, None) when text parses as one function, else (None, 1-based error line)."""
    try:
        body = ast.parse(text).body
    except SyntaxError as exc:
        if "indent" not in str(exc):
            return None, exc.lineno or 1
        try:
            body = ast.parse("if True:\n" + text).body[0].body  # indented method
        except SyntaxError as exc2:
            return None, max((exc2.lineno or 2) - 1, 1)
    except (ValueError, RecursionError):
        return None, 1
    if not body or not isinstance(body[0], _FUNC):
        return None, 1
    return body[0], None


def repair_source(text: str, max_edits: int = 0) -> Optional[Tuple[str, List[int]]]:
    """Return (repaired text, 1-based edited line numbers) or None if no valid function results."""
    lines = text.split("\n")
    limit = max_edits or max(10, len(lines) // 2)
    stage = {}
    edited: List[int] = []
    for _ in range(limit + 1):
        node, err = _error_line("\n".join(lines))
        if node is not None:
            return "\n".join(lines), sorted(set(edited))
        idx = min(max((err or 1) - 1, 0), len(lines) - 1)
        if idx == 0 and lines[0].lstrip().startswith(("def ", "async def ", "@")):
            return None  # the header itself is broken: there is no function left to describe
        level = stage.get(idx, 0)
        if level >= 2:
            return None
        stage[idx] = level + 1
        indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
        lines[idx] = indent + "pass" if level == 0 else ""
        edited.append(idx + 1)
    return None
