"""API/database markers: a small, documented set of operations recognised in function bodies.

A call that matches a marker becomes a `uses_api` edge from the calling unit to the marker label
(`<category>:<name>`, e.g. `db:execute`), with the call-site line and the callee text as detail.

Default marker set
  db:execute        x.execute(...), x.executemany(...), x.executescript(...)   run SQL
  db:cursor         x.cursor(...)                                              open a cursor
  db:commit         x.commit(...)                                              commit a transaction
  file:open         open(...)                                                  open a file (plain call only)
  validation:validate   a call whose function name contains one of the words
                    validate, valid, validation, validator, sanitize, sanitise, sanitizer,
                    verify, verification, check, escape (words are split at `_` and case changes,
                    so `is_valid` and `sanitizeHtml` match, `checksum`, `invalidate` and
                    `validated` do not)

Matching is by name only, from syntax. The receiver of `x.execute(...)` is not checked, so any
object with such a method counts; the name `validate` says what the author intended, not that the
input is actually validated or that validation is effective. A `db:`/`file:` marker is only added
for a call that was not resolved to a function of the corpus (a corpus function named `open` is a
`calls` edge instead). Validation markers are added in either case, so a corpus validator call
carries both a `calls` edge and a `validation:validate` marker at the same line.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

CATEGORIES = ("db", "file", "validation")


@dataclass(frozen=True)
class Marker:
    label: str
    category: str
    description: str
    attr_names: Tuple[str, ...] = ()  # matches x.<name>(...) for any receiver x
    func_names: Tuple[str, ...] = ()  # matches <name>(...) when <name> is not a local name
    name_words: FrozenSet[str] = frozenset()  # matches a callee whose name contains one of these words


DEFAULT_MARKERS: Tuple[Marker, ...] = (
    Marker("db:execute", "db", "run SQL: execute, executemany, executescript",
           attr_names=("execute", "executemany", "executescript")),
    Marker("db:cursor", "db", "open a database cursor", attr_names=("cursor",)),
    Marker("db:commit", "db", "commit a transaction", attr_names=("commit",)),
    Marker("file:open", "file", "open a file (plain open(...) call)", func_names=("open",)),
    Marker("validation:validate", "validation", "call named like a validation step",
           name_words=frozenset({
               "validate", "valid", "validation", "validator", "sanitize", "sanitise", "sanitizer",
               "verify", "verification", "check", "escape",
           })),
)

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def name_words(name: str) -> List[str]:
    """Lower-case words of an identifier: `sanitizeHtml` -> sanitize, html; `is_valid` -> is, valid."""
    return [w.lower() for w in _WORD.findall(name)]


def _callee(call: ast.Call) -> Tuple[Optional[str], bool]:
    """(last name of the callee, True if written as a plain name)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id, True
    if isinstance(func, ast.Attribute):
        return func.attr, False
    return None, False


def match_markers(
    call: ast.Call, local_names: Set[str], markers: Sequence[Marker] = DEFAULT_MARKERS
) -> List[Tuple[Marker, str]]:
    """Markers a call matches, each with the callee text (e.g. `db.execute`)."""
    name, plain = _callee(call)
    if name is None:
        return []
    detail = ast.unparse(call.func)
    words = set(name_words(name))
    found: List[Tuple[Marker, str]] = []
    for marker in markers:
        if plain:
            hit = name in marker.func_names and name not in local_names
        else:
            hit = name in marker.attr_names
        if not hit and marker.name_words and words & marker.name_words:
            hit = True
        if hit:
            found.append((marker, detail))
    return found


def describe_markers(markers: Sequence[Marker] = DEFAULT_MARKERS) -> List[Dict[str, str]]:
    """One row per marker for display and documentation."""
    rows = []
    for m in markers:
        patterns = [f"x.{n}(...)" for n in m.attr_names] + [f"{n}(...)" for n in m.func_names]
        if m.name_words:
            patterns.append("name contains: " + ", ".join(sorted(m.name_words)))
        rows.append({"label": m.label, "category": m.category, "matches": "; ".join(patterns),
                     "description": m.description})
    return rows
