"""A tiny structural pattern language over fragment terms.

  Label                 the function has such a node          Call:open
  A // B                an A contains a B (any depth)         For//Try      With//Call:open
  A > B                 a B is a direct (kept) child of an A  Try>ExceptHandler
  A => B                an A ends before a B starts           If=>Call:execute
  !pattern              none of it may hold                   !With//Call:open
  p1 or p2              either may hold                       Call:execute//BinOp:Add or BinOp:Add=>Call:execute
  A|B                   either label (inside a pattern)       For|While//Try
  c1 and c2             all clauses must hold                 Call:open and !With//Call:open
                        ('!' and 'or' apply within one clause; 'and' binds loosest)

Labels are the base kinds (If For While Try ExceptHandler With Return Raise Assert Delete Assign
AugAssign AnnAssign Import Pass Break Continue Call BinOp BoolOp UnaryOp Compare IfExp Subscript
JoinedStr Await Yield Comprehension Lambda FunctionDef ClassDef Match), optionally with a specific
suffix for Call (name, or dotted name), BinOp (Add, Mod, ...), UnaryOp, ExceptHandler (type or
'bare') and Raise (exception type). '=>' works for the labels in ORD_BASES only. Case of the base
label does not matter ('for' == 'For').

One pattern string is one Relation and is scored as a single requirement; several --pattern flags
are separate requirements, each worth its own share of the score. Matching is a set lookup in the
unit's fragment terms, so it never re-parses code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import product
from typing import Iterable, List, Mapping, Optional, Tuple

from structsearch.parsing.fragments import (
    BASE_LABELS,
    ORD_BASES,
    SPECIFIC_BASES,
    canonical_base,
    canonical_specific,
)

MAX_PATTERN_CHARS = 300
MAX_ATOMS = 64

_OP_NAME = {"//": "contains", ">": "child", "=>": "before"}


class PatternError(ValueError):
    """A pattern string could not be parsed or names an unknown label."""


@dataclass(frozen=True)
class Atom:
    op: str  # "has" | "contains" | "child" | "before"
    a: str
    b: Optional[str] = None

    @property
    def term(self) -> str:
        if self.op == "has":
            return f"u:{self.a}"
        if self.op == "contains":
            return f"ad:{self.a}//{self.b}"
        if self.op == "child":
            return f"pc:{self.a}>{self.b}"
        return f"ord:{self.a}=>{self.b}"


@dataclass(frozen=True)
class Clause:
    """Holds when any atom's term is present (or, if negated, when none is)."""

    atoms: Tuple[Atom, ...]
    negate: bool = False


@dataclass(frozen=True)
class Relation:
    """One structural requirement: every clause must hold."""

    clauses: Tuple[Clause, ...]
    text: str = ""  # canonical pattern string
    reason: str = ""  # human wording for evidence; defaults to the text
    weight: float = 1.0

    @property
    def atoms(self) -> Tuple[Atom, ...]:
        return tuple(atom for clause in self.clauses for atom in clause.atoms)

    def with_reason(self, reason: str) -> "Relation":
        return replace(self, reason=reason)

    def to_dict(self):
        return {"pattern": self.text, "reason": self.reason, "weight": self.weight}


def _label(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise PatternError("empty label")
    base_raw, colon, spec = raw.partition(":")
    base = canonical_base(base_raw.strip())
    if base is None:
        raise PatternError(f"unknown label '{base_raw.strip()}' (known: {', '.join(BASE_LABELS)})")
    if not colon:
        return base
    if base not in SPECIFIC_BASES:
        raise PatternError(f"'{base}' has no ':' variants (only {', '.join(SPECIFIC_BASES)})")
    clean = canonical_specific(base, spec.strip())
    if clean is None:
        raise PatternError(f"'{spec.strip()}' is not valid after '{base}:'")
    return f"{base}:{clean}"


def _labels(raw: str) -> List[str]:
    return list(dict.fromkeys(_label(part) for part in raw.split("|")))


def _split_op(chunk: str) -> Tuple[str, str, Optional[str]]:
    parts = re.split(r"(=>|//|>)", chunk)
    if len(parts) == 1:
        return "", chunk, None
    if len(parts) != 3:
        raise PatternError(f"use only one operator per alternative: '{chunk.strip()}'")
    return parts[1], parts[0], parts[2]


def _parse_clause(raw: str) -> Tuple[Clause, str]:
    raw = raw.strip()
    negate = False
    if raw.startswith("!"):
        negate, raw = True, raw[1:].strip()
    elif raw.lower().startswith("not "):
        negate, raw = True, raw[4:].strip()
    atoms: List[Atom] = []
    chunks: List[str] = []
    for chunk in re.split(r"\s+or\s+", raw, flags=re.IGNORECASE):
        op, left, right = _split_op(chunk)
        lefts = _labels(left)
        if not op:
            atoms.extend(Atom("has", a) for a in lefts)
            chunks.append("|".join(lefts))
            continue
        rights = _labels(right or "")
        for a, b in product(lefts, rights):
            if op == "=>":
                for label in (a, b):
                    if label.split(":", 1)[0] not in ORD_BASES:
                        raise PatternError(
                            f"'=>' needs ordering-relevant labels; '{label}' is not one of: {', '.join(sorted(ORD_BASES))}"
                        )
            atoms.append(Atom(_OP_NAME[op], a, b))
        chunks.append("|".join(lefts) + op + "|".join(rights))
    text = ("!" if negate else "") + " or ".join(dict.fromkeys(chunks))
    return Clause(tuple(dict.fromkeys(atoms)), negate), text


def parse_pattern(text: str) -> Relation:
    """Parse one pattern. Raises PatternError with a readable message."""
    if not isinstance(text, str):
        raise PatternError("a pattern must be a string")
    raw = text.strip()
    if not raw:
        raise PatternError("empty pattern")
    if len(raw) > MAX_PATTERN_CHARS:
        raise PatternError("pattern is too long")
    clauses: List[Clause] = []
    texts: List[str] = []
    for part in re.split(r"\s+and\s+", raw, flags=re.IGNORECASE):
        clause, clause_text = _parse_clause(part)
        if clause_text not in texts:
            clauses.append(clause)
            texts.append(clause_text)
    if sum(len(c.atoms) for c in clauses) > MAX_ATOMS:
        raise PatternError("pattern expands to too many alternatives")
    canonical = " and ".join(texts)
    return Relation(tuple(clauses), canonical, canonical)


def parse_patterns(texts: Iterable[str]) -> List[Relation]:
    return [parse_pattern(t) for t in texts]


def _clause_holds(clause: Clause, terms: Mapping[str, int]) -> bool:
    found = any(atom.term in terms for atom in clause.atoms)
    return (not found) if clause.negate else found


def holds(relation: Relation, terms: Mapping[str, int]) -> bool:
    return all(_clause_holds(clause, terms) for clause in relation.clauses)


def witnesses(relation: Relation, terms: Mapping[str, int]) -> List[str]:
    """Terms that make the positive clauses true (for evidence); negated clauses have none."""
    return [
        atom.term
        for clause in relation.clauses
        if not clause.negate
        for atom in clause.atoms
        if atom.term in terms
    ]
