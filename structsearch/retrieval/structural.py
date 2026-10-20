"""Structural retrieval: query -> constraints on AST features -> compatibility score per unit.

A query like "recursive tree traversal without error handling" carries structural wishes
(calls itself, has no try/except) next to topical words (tree, traversal). The mapper turns the
structural part into a *profile*: a short list of constraints over the named features from
structsearch.parsing. Each unit is then scored by how well its features satisfy the profile.

Relations (patterns.py) add *how the parts are arranged*: "a try inside a loop", "open() outside a
with", "string building before execute". They are checked against the fragment terms of each unit
(parsing/fragments.py) and count as one more constraint each in the weighted average.

Two mappers produce profiles:
  rules_profile   deterministic phrase lexicon with negation handling (always available)
  llm_profile     optional local Ollama model returning schema-constrained JSON; every answer is
                  validated against FEATURE_NAMES, and anything unusable falls back to the rules.

Constraint operators (score in [0, 1] per constraint, weighted average per unit):
  present   sum of the features >= 1                      1 or 0
  absent    sum of the features == 0                      1 or 0
  at_least  sum >= value                                  min(sum / value, 1)
  at_most   sum <= value                                  1, else value / sum
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from structsearch.ingestion.corpus import FailedFile
from structsearch.llm.ollama import LLMError, LLMSettings, ModelMissingError, OllamaJSON
from structsearch.parsing.features import FEATURE_DOC, FEATURE_NAMES
from structsearch.parsing.fragments import BASE_LABELS, FragmentRecord, describe_term
from structsearch.retrieval.patterns import PatternError, Relation, holds, parse_pattern, witnesses
from structsearch.schemas import PARSE_OK, AstRecord, CodeUnit, RankedResult

OPS = ("present", "absent", "at_least", "at_most")
MAX_CONSTRAINTS = 8
MAX_RELATIONS = 4
MAX_VALUE = 1000.0


# --------------------------------------------------------------------------- data


@dataclass(frozen=True)
class Constraint:
    """A wish about the *sum* of one or more features (several features = 'any of these')."""

    features: Tuple[str, ...]
    op: str = "present"
    value: float = 1.0  # threshold for at_least / at_most
    weight: float = 1.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "features": list(self.features),
            "op": self.op,
            "value": self.value,
            "weight": self.weight,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ConstraintProfile:
    constraints: Tuple[Constraint, ...] = ()
    source: str = "rules"  # "rules" or "llm:<model>"
    fallback_reason: Optional[str] = None  # set when the LLM was requested but the rules were used
    relations: Tuple[Relation, ...] = ()  # arrangement patterns, e.g. For//Try

    @property
    def is_empty(self) -> bool:
        return not self.constraints and not self.relations

    def with_relations(self, extra: Sequence[Relation]) -> "ConstraintProfile":
        merged = list(self.relations)
        merged.extend(r for r in extra if all(r.text != m.text for m in merged))
        return ConstraintProfile(self.constraints, self.source, self.fallback_reason, tuple(merged))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "fallback_reason": self.fallback_reason,
            "constraints": [c.to_dict() for c in self.constraints],
            "patterns": [r.to_dict() for r in self.relations],
        }

    def describe(self) -> str:
        if self.is_empty:
            return "no structural requirements found in the query"
        parts = [c.reason or f"{c.op} {'+'.join(c.features)}" for c in self.constraints]
        parts += [r.reason or r.text for r in self.relations]
        return "; ".join(parts)


@dataclass
class UnitMatch:
    score: float
    # (constraint, feature sum) for count constraints; (relation, 1.0 / 0.0) for patterns
    matched: List[Tuple[Union[Constraint, Relation], float]] = field(default_factory=list)
    missed: List[Tuple[Union[Constraint, Relation], float]] = field(default_factory=list)
    witness_terms: List[str] = field(default_factory=list)  # fragment terms that satisfied patterns


# --------------------------------------------------------------------------- scoring


def feature_sum(features: Mapping[str, float], names: Sequence[str]) -> float:
    return float(sum(features.get(name, 0.0) for name in names))


def constraint_score(constraint: Constraint, value: float) -> float:
    op = constraint.op
    if op == "present":
        return 1.0 if value >= 1.0 else 0.0
    if op == "absent":
        return 1.0 if value <= 0.0 else 0.0
    if op == "at_least":
        return min(value / constraint.value, 1.0) if constraint.value > 0 else 1.0
    if op == "at_most":
        if value <= constraint.value:
            return 1.0
        return constraint.value / value if constraint.value > 0 else 0.0
    raise ValueError(f"unknown constraint operator: {op}")


def match_unit(
    profile: ConstraintProfile,
    features: Mapping[str, float],
    terms: Optional[Mapping[str, int]] = None,
) -> UnitMatch:
    """Weighted average over count constraints and patterns; 0 when the profile is empty.

    `terms` are the unit's fragment terms. Without them patterns cannot be checked and count as unmet.
    """
    total_weight = sum(c.weight for c in profile.constraints) + sum(r.weight for r in profile.relations)
    if total_weight <= 0:
        return UnitMatch(0.0)
    result = UnitMatch(0.0)
    score = 0.0
    for constraint in profile.constraints:
        value = feature_sum(features, constraint.features)
        part = constraint_score(constraint, value)
        score += constraint.weight * part
        (result.matched if part >= 1.0 else result.missed).append((constraint, value))
    for relation in profile.relations:
        ok = terms is not None and holds(relation, terms)
        if ok:
            score += relation.weight
            result.witness_terms.extend(witnesses(relation, terms or {}))
        (result.matched if ok else result.missed).append((relation, 1.0 if ok else 0.0))
    result.score = score / total_weight
    return result


def structural_scores(
    profile: ConstraintProfile,
    records: Sequence[AstRecord],
    fragments: Optional[Sequence[FragmentRecord]] = None,
) -> Dict[str, float]:
    """unit_id -> score for every unit (0.0 for units whose file did not parse). Used by fusion."""
    terms_by_id = {f.unit_id: f.terms for f in fragments or ()}
    return {
        r.unit_id: (match_unit(profile, r.features, terms_by_id.get(r.unit_id)).score if r.parse_status == PARSE_OK else 0.0)
        for r in records
    }


def match_evidence(match: UnitMatch) -> List[str]:
    lines = []
    for label, entries in (("match", match.matched), ("miss", match.missed)):
        for item, value in entries:
            if isinstance(item, Relation):
                shown = item.reason or item.text
                lines.append(f"structural {label}: {shown} [pattern: {item.text}]")
            else:
                lines.append(f"structural {label}: {item.reason or item.op} ({'+'.join(item.features)}={value:g})")
    if match.witness_terms:
        lines.append("structure found: " + "; ".join(describe_term(t) for t in dict.fromkeys(match.witness_terms)))
    return lines


def structural_search(
    profile: ConstraintProfile,
    units_by_id: Mapping[str, CodeUnit],
    records: Sequence[AstRecord],
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Optional[Mapping[str, FailedFile]] = None,  # accepted for symmetry; failed units never match
    fragments: Optional[Sequence[FragmentRecord]] = None,
) -> List[RankedResult]:
    """Top-k units by structural compatibility alone (score > 0 only).

    Structural scores are coarse (many units tie), so this mode is a diagnostic and a building
    block: it shows what the structure signal contributes before it is fused with text.
    """
    terms_by_id = {f.unit_id: f.terms for f in fragments or ()}
    scored = []
    for record in records:
        if record.parse_status != PARSE_OK or record.unit_id not in units_by_id:
            continue
        match = match_unit(profile, record.features, terms_by_id.get(record.unit_id))
        if match.score > 0:
            scored.append((record.unit_id, match))
    scored.sort(key=lambda item: (-item[1].score, item[0]))
    return [
        RankedResult(
            query_id=query_id,
            unit_id=unit_id,
            text_score=0.0,
            structural_score=match.score,
            graph_score=None,
            final_score=match.score,
            evidence=match_evidence(match),
        )
        for unit_id, match in scored[: max(k, 0)]
    ]


# --------------------------------------------------------------------------- rule-based mapper

LOOPS = ("for_count", "while_count")
VALIDATION = ("guard_clause_count", "raise_in_if_count", "type_check_count")


def _c(features: Sequence[str], op: str, reason: str, value: float = 1.0) -> Constraint:
    return Constraint(tuple(features), op, value, 1.0, reason)


@dataclass(frozen=True)
class Rule:
    pattern: "re.Pattern[str]"
    positive: Tuple[Union[Constraint, Relation], ...]
    negative: Tuple[Union[Constraint, Relation], ...] = ()
    inherent_negative: bool = False  # words like "unvalidated" already say "no ..."


def _rule(
    pattern: str,
    positive: Sequence[Union[Constraint, Relation]],
    negative: Sequence[Union[Constraint, Relation]] = (),
    inherent: bool = False,
) -> Rule:
    return Rule(re.compile(pattern), tuple(positive), tuple(negative), inherent)


def _p(text: str, reason: str) -> Relation:
    """A pattern relation with a human-readable reason (parsed once, at import)."""
    return parse_pattern(text).with_reason(reason)


_EXEC = "Call:execute|Call:executemany|Call:executescript"
_BUILT = "BinOp:Add|BinOp:Mod|JoinedStr|Call:format"
SQL_BUILT_PATTERN = f"{_EXEC}//{_BUILT} or {_BUILT}=>{_EXEC}"
_SQL_REASON = "SQL built by string concatenation/formatting"
_LOOP_WORD = r"(?:a |an |the |each |every )?(?:for[- ]?|while[- ]?)?loops?"


# Order matters: specific phrases come before generic ones, because a matched span is consumed.
RULES: Tuple[Rule, ...] = (
    # --- arrangement patterns (relations between parts) ---
    _rule(r"\b(?:try(?:/|[- ])except|try|except|error handling|exception handling|exception handlers?|catch\w*)\s+"
          r"(?:blocks?\s+)?(?:inside|within|in|inside of)\s+" + _LOOP_WORD + r"\b|"
          r"\bloops?\s+(?:that |which )?(?:contains?|containing|has|have|with|includ\w+|wraps?|wrapping)\s+"
          r"(?:a |an )?(?:try(?:/|[- ])except|try|error handling|exception handling)\b",
          [_p("For|While//Try", "error handling inside a loop")],
          [_p("!For|While//Try", "no error handling inside a loop")]),
    _rule(r"\b(?:opens?|reads?|writes?|opening|reading|writing)\s+(?:a |an |the |some )?(?:files?|handles?)\s+"
          r"(?:without|not using|outside(?: of)?)\s+(?:a |an |the )?(?:with|context manager|with[- ]statements?)\b|"
          r"\bunclosed\s+files?\b|\bfile\s+(?:handle\s+)?leaks?\b|\bleak\w*\s+(?:a\s+)?file\b|"
          r"\bforgets?\s+to\s+close\b|\bnever\s+closes?\b",
          [_p("Call:open and !With//Call:open", "open() outside a with block")],
          [_p("With//Call:open", "open() inside a with block")]),
    _rule(r"\b(?:opens?|reads?|writes?|opening|reading|writing)\s+(?:a |an |the |some )?(?:files?|handles?)\s+"
          r"(?:using|with|via|in|inside)\s+(?:a |an |the )?(?:with|context manager|with[- ]statements?)\b",
          [_p("With//Call:open", "open() inside a with block")],
          [_p("!With//Call:open", "no open() inside a with block")]),
    _rule(r"\bsql[- ]?injection\b|\b(?:sql|quer(?:y|ies))\s+(?:built|constructed|formed|assembled|composed|created)\s+"
          r"(?:with|using|by|from)\s+(?:string\s+)?(?:concatenat\w+|formatting|format|f-?strings?|interpolat\w+)\b|"
          r"\bstring[- ](?:concatenat\w+|formatting)\s+in\s+(?:an?\s+)?(?:sql|quer\w+)\b|\bunparameteri[sz]ed\b",
          [_p(SQL_BUILT_PATTERN, _SQL_REASON)],
          [_p("!" + SQL_BUILT_PATTERN, "SQL not built by string formatting")]),
    _rule(r"\bparameteri[sz]ed\b|\bprepared statements?\b|\bbound parameters?\b",
          [_p(f"{_EXEC} and !{SQL_BUILT_PATTERN}", "query executed without string building")],
          [_p(SQL_BUILT_PATTERN, _SQL_REASON)]),
    _rule(r"\beval\b|\bexec\b|\bdynamic code execution\b|\bcode injection\b",
          [_p("Call:eval|Call:exec", "calls eval/exec")],
          [_p("!Call:eval|Call:exec", "does not call eval/exec")]),
    _rule(r"\b(?:early[- ])?returns?\s+(?:inside|within|in|from)\s+" + _LOOP_WORD + r"\b",
          [_p("For|While//Return", "return inside a loop")],
          [_p("!For|While//Return", "no return inside a loop")]),
    # --- counts and flags ---
    _rule(r"\bnested (?:for |while )?loops?\b|\bloops? (?:within|inside) loops?\b|\bdouble loops?\b",
          [_c(["max_loop_depth"], "at_least", "nested loops", 2)],
          [_c(["max_loop_depth"], "at_most", "no nested loops", 1)]),
    _rule(r"\bdeeply nested\b(?:\s+(?:conditionals?|ifs?|branch\w*|code|logic|structures?))?|\bdeep nesting\b|"
          r"\bnested (?:conditionals?|ifs?|branch\w*)\b",
          [_c(["max_depth"], "at_least", "deep nesting", 3)],
          [_c(["max_depth"], "at_most", "shallow nesting", 2)]),
    _rule(r"\bnested (?:functions?|defs?)\b|\binner functions?\b|\bclosures?\b",
          [_c(["nested_def_count"], "present", "nested function")],
          [_c(["nested_def_count"], "absent", "no nested function")]),
    _rule(r"\bbare excepts?\b|\bcatch[- ]all\b|\bswallow\w*\b|\bsilently (?:ignor\w+|catch\w*|pass\w*)\b",
          [_c(["bare_except_count"], "present", "bare except / swallowed errors")],
          [_c(["bare_except_count"], "absent", "no bare except")]),
    _rule(r"\bunhandled\b|\buncaught\b|\bunprotected\b",
          [], [_c(["try_count"], "absent", "no error handling")], inherent=True),
    _rule(r"\b(?:error|exception|failure)s?[- ]handl\w+|\bhandl\w+ (?:errors?|exceptions?|failures?)\b|"
          r"\btry[ /-]*(?:except|catch)\b|\bcatch(?:es)? (?:errors?|exceptions?)\b|\bcatch(?:es)?\b|\btry\b",
          [_c(["try_with_handler_count"], "present", "error handling (try/except)")],
          [_c(["try_count"], "absent", "no error handling")]),
    _rule(r"\bfinally\b|\bclean[- ]?up\b",
          [_c(["finally_count"], "present", "cleanup in finally")],
          [_c(["finally_count"], "absent", "no finally block")]),
    _rule(r"\braises?\b|\braising\b|\bthrows?\b",
          [_c(["raise_count"], "present", "raises an exception")],
          [_c(["raise_count"], "absent", "does not raise")]),
    _rule(r"\bunvalidated\b|\bunchecked\b|\bunsanitiz?ed\b|\bunsanitised\b|\bunguarded\b|\bunverified\b",
          [], [_c(VALIDATION, "absent", "no input validation")], inherent=True),
    _rule(r"\bvalidat\w+|\bsanitiz\w+|\bsanitis\w+|\binput checks?\b|\bchecks? (?:the )?(?:input|argument|parameter)s?\b|"
          r"\bguard clauses?\b|\bprecondition\w*|\bverif(?:y|ies|ication)\b",
          [_c(VALIDATION, "present", "input validation (guard / type check)")],
          [_c(VALIDATION, "absent", "no input validation")]),
    _rule(r"\btype[- ]check\w*|\bisinstance\b|\bissubclass\b|\bchecks? (?:the )?types?\b",
          [_c(["type_check_count"], "present", "type check")],
          [_c(["type_check_count"], "absent", "no type check")]),
    _rule(r"\brecurs\w*|\bcalls? (?:itself|themselves)\b|\bself[- ]referential\b",
          [_c(["self_call"], "present", "recursion")],
          [_c(["self_call"], "absent", "not recursive")]),
    _rule(r"\bwhile[- ]loops?\b",
          [_c(["while_count"], "present", "while loop")],
          [_c(["while_count"], "absent", "no while loop")]),
    _rule(r"\bfor[- ]loops?\b",
          [_c(["for_count"], "present", "for loop")],
          [_c(["for_count"], "absent", "no for loop")]),
    _rule(r"\bloop(?:s|ing)?\b|\biterat\w+|\bfor[- ]?each\b|\brepeatedly\b",
          [_c(LOOPS, "present", "uses a loop")],
          [_c(LOOPS, "absent", "no loop")]),
    _rule(r"\basync\w*|\bawait\w*|\bcoroutines?\b",
          [_c(["is_async"], "present", "async function")],
          [_c(["is_async"], "absent", "not async")]),
    _rule(r"\bgenerators?\b|\byield\w*|\blazily\b",
          [_c(["is_generator"], "present", "generator")],
          [_c(["is_generator"], "absent", "not a generator")]),
    _rule(r"\bcontext managers?\b|\bwith[- ](?:statements?|blocks?)\b|"
          r"\bclos(?:e|es|ing) (?:the |a )?(?:files?|connections?|resources?)\b",
          [_c(["with_count"], "present", "with statement / context manager")],
          [_c(["with_count"], "absent", "no with statement")]),
    _rule(r"\bassert\w*",
          [_c(["assert_count"], "present", "assertion")],
          [_c(["assert_count"], "absent", "no assertion")]),
    _rule(r"\bdecorat\w+",
          [_c(["decorator_count"], "present", "decorated")],
          [_c(["decorator_count"], "absent", "not decorated")]),
    _rule(r"\blambdas?\b|\banonymous functions?\b",
          [_c(["lambda_count"], "present", "lambda")],
          [_c(["lambda_count"], "absent", "no lambda")]),
    _rule(r"\bcomprehensions?\b",
          [_c(["comprehension_count"], "present", "comprehension")],
          [_c(["comprehension_count"], "absent", "no comprehension")]),
    _rule(r"\bconditionals?\b|\bbranch\w*|\bif[- /]else\b|\bif statements?\b",
          [_c(["if_count"], "present", "conditional logic")],
          [_c(["if_count"], "absent", "no conditionals")]),
)

_NEGATOR = re.compile(
    r"(?:\b(?:without|no|not|never|missing|lacks?|lacking|w/o|absence of|cannot|isn't|doesn't|don't|"
    r"aren't|fails? to|failing to)\b|n't\b)"
    r"(?:\s+(?!(?:but|and|or|yet|while|although)\b)[\w'-]+){0,2}\s*$"
)


def _is_negated(prefix: str) -> bool:
    return _NEGATOR.search(prefix) is not None


# Words that name a kind of code part, for the generic "X before / after / inside / containing Y" reading.
_EXEC_LABELS = "Call:execute|Call:executemany|Call:executescript"
_CHECK_LABELS = "If|Assert"
VOCAB: Dict[str, str] = {
    "function call": "Call", "function calls": "Call", "call": "Call", "calls": "Call",
    "execute": _EXEC_LABELS, "executes": _EXEC_LABELS, "execution": _EXEC_LABELS,
    "query": _EXEC_LABELS, "queries": _EXEC_LABELS, "db call": _EXEC_LABELS,
    "open": "Call:open", "opens": "Call:open", "eval": "Call:eval|Call:exec",
    "for loop": "For", "for loops": "For", "while loop": "While", "while loops": "While",
    "loop": "For|While", "loops": "For|While", "iteration": "For|While",
    "try except": "Try", "try/except": "Try", "try block": "Try", "try": "Try", "error handling": "Try",
    "exception handling": "Try", "except block": "ExceptHandler", "except": "ExceptHandler",
    "exception handler": "ExceptHandler", "handler": "ExceptHandler",
    "if statement": "If", "if": "If", "condition": "If", "conditional": "If", "branch": "If",
    "check": _CHECK_LABELS, "checks": _CHECK_LABELS, "validation": _CHECK_LABELS, "validate": _CHECK_LABELS,
    "guard": _CHECK_LABELS, "guard clause": _CHECK_LABELS, "assertion": "Assert", "assert": "Assert",
    "raise": "Raise", "raises": "Raise", "throw": "Raise", "throws": "Raise",
    "return": "Return", "returns": "Return",
    "with statement": "With", "with block": "With", "context manager": "With",
    "string concatenation": "BinOp:Add|BinOp:Mod|JoinedStr|Call:format", "concatenation": "BinOp:Add|BinOp:Mod|JoinedStr|Call:format",
    "string formatting": "BinOp:Add|BinOp:Mod|JoinedStr|Call:format", "formatting": "BinOp:Add|BinOp:Mod|JoinedStr|Call:format",
    "f-string": "JoinedStr", "string building": "BinOp:Add|BinOp:Mod|JoinedStr|Call:format",
    "await": "Await", "yield": "Yield", "assignment": "Assign", "import": "Import",
}
# relation word -> (operator, swap): "A before B" is A=>B; "A after B" is B=>A; "A inside B" is B//A.
RELATION_WORDS: Dict[str, Tuple[str, bool]] = {
    "before": ("=>", False), "prior to": ("=>", False), "ahead of": ("=>", False),
    "after": ("=>", True), "following": ("=>", True),
    "inside of": ("//", True), "inside": ("//", True), "within": ("//", True), "in": ("//", True),
    "nested in": ("//", True), "nested within": ("//", True),
    "containing": ("//", False), "contains": ("//", False), "that contains": ("//", False),
    "which contains": ("//", False), "that has": ("//", False), "having": ("//", False),
    "with a": ("//", False), "with an": ("//", False),
}
_alt = lambda words: "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))  # noqa: E731
_RELATIONAL = re.compile(
    rf"\b(?P<a>{_alt(VOCAB)})\s+(?P<op>{_alt(RELATION_WORDS)})\s+(?:(?:a|an|the|each|every|any)\s+)?(?P<b>{_alt(VOCAB)})\b"
)


def _relational_matches(text: str) -> List[Tuple[int, int, Relation, Relation]]:
    """'call before execute', 'try inside a loop', 'loop containing a call' -> (start, end, positive, negated)."""
    out = []
    for match in _RELATIONAL.finditer(text):
        a_words, b_words = match.group("a"), match.group("b")
        op, swap = RELATION_WORDS[match.group("op")]
        left, right = VOCAB[a_words], VOCAB[b_words]
        if swap:
            left, right = right, left
        try:
            positive = parse_pattern(f"{left}{op}{right}")
        except PatternError:  # e.g. '=>' with labels that have no meaningful order
            continue
        reason = f"{a_words} {match.group('op')} {b_words}"
        out.append((match.start(), match.end(), positive.with_reason(reason),
                    parse_pattern(f"!{left}{op}{right}").with_reason(f"no: {reason}")))
    return out


def rules_profile(query: str) -> ConstraintProfile:
    """Deterministic query -> profile. Unknown wording simply yields fewer (or no) constraints."""
    text = query.lower()
    consumed: List[Tuple[int, int]] = []
    found: List[Tuple[int, Tuple[Union[Constraint, Relation], ...]]] = []
    for start, end, positive, negative in _relational_matches(text):
        if any(start < c_end and c_start < end for c_start, c_end in consumed):
            continue
        consumed.append((start, end))
        found.append((start, (negative,) if _is_negated(text[:start]) else (positive,)))
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            span = (match.start(), match.end())
            if any(span[0] < end and start < span[1] for start, end in consumed):
                continue
            consumed.append(span)
            negated = rule.inherent_negative or _is_negated(text[: match.start()])
            found.append((match.start(), rule.negative if negated else rule.positive))
    found.sort(key=lambda item: item[0])  # show constraints in the order the user wrote them
    items = [c for _, group in found for c in group]
    unique: List[Constraint] = []
    relations: List[Relation] = []
    for item in items:  # one constraint per feature group / pattern text; the first reading wins
        if isinstance(item, Relation):
            if all(item.text != other.text for other in relations):
                relations.append(item)
        elif all(item.features != other.features for other in unique):
            unique.append(item)
    # "iterates with a for loop": the explicit wish already implies the generic "uses a loop"
    unique = [
        c for c in unique
        if not (c.op == "present" and any(
            o is not c and o.op == "present" and set(o.features) < set(c.features) for o in unique))
    ]
    return ConstraintProfile(tuple(unique[:MAX_CONSTRAINTS]), source="rules", relations=tuple(relations[:MAX_RELATIONS]))


# --------------------------------------------------------------------------- LLM mapper


def llm_schema() -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "features": {"type": "array", "items": {"type": "string", "enum": list(FEATURE_NAMES)}},
                        "op": {"type": "string", "enum": list(OPS)},
                        "value": {"type": "number"},
                        "weight": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["features", "op"],
                },
            }
        },
        "required": ["constraints"],
    }
    schema["properties"]["patterns"] = {"type": "array", "items": {"type": "string"}}
    return schema


def llm_prompt(query: str) -> str:
    features = "\n".join(f"- {name}: {doc}" for name, doc in FEATURE_DOC.items())
    return (
        "You translate a code-search query into structural requirements on Python functions.\n"
        "Return JSON with two lists.\n\n"
        "1) \"constraints\": counts over these feature names (use ONLY these names):\n"
        f"{features}\n"
        "Operators: present (sum of features >= 1), absent (sum == 0), at_least / at_most (use 'value').\n"
        "Several names in 'features' mean 'any of them'.\n\n"
        "2) \"patterns\": strings describing how parts are ARRANGED, in this mini language:\n"
        "  Label                 function has such a node        e.g. Call:open\n"
        "  A // B                A contains B (any depth)        e.g. For//Try   With//Call:open\n"
        "  A > B                 B is a direct child of A        e.g. Try>ExceptHandler\n"
        "  A => B                A ends before B starts          e.g. If=>Call:execute\n"
        "  !pattern              must NOT hold                   e.g. !With//Call:open\n"
        "  p1 or p2              either one                      A|B inside a pattern also means either\n"
        "  c1 and c2             both clauses must hold          e.g. Call:open and !With//Call:open\n"
        f"Labels: {', '.join(BASE_LABELS)}. Call, BinOp, UnaryOp, ExceptHandler and Raise take a suffix: "
        "Call:open, Call:os.system, BinOp:Add, BinOp:Mod, ExceptHandler:bare, ExceptHandler:ValueError, Raise:ValueError. "
        "'=>' only works for If For While Try ExceptHandler With Raise Assert Return Call Await Yield BinOp JoinedStr Delete Import.\n"
        "A requirement like 'X without Y' is ONE pattern: 'X and !Y' (or 'X and !A//X' for 'X not inside A').\n\n"
        "Include only requirements about code STRUCTURE. Ignore topical words such as file, user, tree, database. "
        "If there is none return {\"constraints\": [], \"patterns\": []}.\n\n"
        "Examples:\n"
        "Query: recursive tree traversal\n"
        '{"constraints": [{"features": ["self_call"], "op": "present", "reason": "recursion"}], "patterns": []}\n'
        "Query: read a file without error handling\n"
        '{"constraints": [{"features": ["try_count"], "op": "absent", "reason": "no error handling"}], "patterns": []}\n'
        "Query: retries inside a loop that catches exceptions\n"
        '{"constraints": [], "patterns": ["For|While//Try"]}\n'
        "Query: opens a file but never closes it properly\n"
        '{"constraints": [], "patterns": ["Call:open and !With//Call:open"]}\n'
        "Query: parse a csv\n"
        '{"constraints": [], "patterns": []}\n\n'
        f"Query: {query}\n"
    )


def _number(raw: Any, default: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    if raw != raw or raw in (float("inf"), float("-inf")):  # NaN / infinity
        return default
    return float(raw)


def _constraint_items(data: Any) -> List[Any]:
    if isinstance(data, dict) and "constraints" not in data and "patterns" in data:
        return []  # patterns-only answer
    items = data.get("constraints") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected an object with a 'constraints' list")
    return items


def _valid_constraints(items: List[Any]) -> List[Constraint]:
    out: List[Constraint] = []
    for item in items[: MAX_CONSTRAINTS * 2]:
        if not isinstance(item, dict):
            continue
        names = item.get("features", item.get("feature"))
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n in FEATURE_DOC for n in names):
            continue
        op = item.get("op")
        if op not in OPS:
            continue
        value = min(max(_number(item.get("value"), 1.0), 0.0), MAX_VALUE)
        if op == "at_least" and value <= 0:
            value = 1.0
        weight = _number(item.get("weight"), 1.0)
        weight = weight if 0 < weight <= 1 else 1.0
        reason = item.get("reason") if isinstance(item.get("reason"), str) else ""
        constraint = Constraint(tuple(dict.fromkeys(names)), op, value, weight, reason.strip()[:80])
        if constraint not in out:
            out.append(constraint)
    return out[:MAX_CONSTRAINTS]


def parse_llm_constraints(data: Any) -> List[Constraint]:
    """Validate the count constraints. Unknown features / operators drop that constraint.

    ValueError when the answer is malformed or none of its constraints is usable.
    """
    items = _constraint_items(data)
    out = _valid_constraints(items)
    if items and not out:
        raise ValueError("the model's constraints used unknown features or operators")
    return out


def parse_llm_patterns(data: Any) -> List[Relation]:
    """Validate the arrangement patterns; invalid ones are dropped. ValueError if patterns existed but none parse."""
    raw = data.get("patterns") if isinstance(data, dict) else None
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("'patterns' must be a list of strings")
    out: List[Relation] = []
    for text in raw[: MAX_RELATIONS * 2]:
        try:
            relation = parse_pattern(text)
        except PatternError:
            continue
        if all(relation.text != other.text for other in out):
            out.append(relation)
    if raw and not out:
        raise ValueError("the model's patterns could not be parsed")
    return out[:MAX_RELATIONS]


def parse_llm_output(data: Any) -> Tuple[List[Constraint], List[Relation]]:
    """Both lists; an error only if the model proposed something and none of it was usable."""
    items = _constraint_items(data)
    constraints = _valid_constraints(items)
    try:
        relations = parse_llm_patterns(data)
    except ValueError:
        if not constraints:
            raise
        relations = []
    if items and not constraints and not relations:
        raise ValueError("the model's constraints used unknown features or operators")
    return constraints, relations


def llm_profile(query: str, settings: LLMSettings, client_factory: Optional[Callable[[str], Any]] = None) -> ConstraintProfile:
    """Ask the local model. Raises LLMError / ValueError; build_profile turns those into a fallback."""
    factory = client_factory or (lambda model: OllamaJSON(model, settings.host, settings.timeout_seconds))
    models = [settings.model]
    if settings.fallback_model and settings.fallback_model != settings.model:
        models.append(settings.fallback_model)
    last_error: Optional[LLMError] = None
    for model in models:
        try:
            data = factory(model).generate_json(llm_prompt(query), llm_schema())
        except ModelMissingError as exc:  # try the smaller model before giving up
            last_error = exc
            continue
        constraints, relations = parse_llm_output(data)
        return ConstraintProfile(tuple(constraints), source=f"llm:{model}", relations=tuple(relations))
    raise last_error or LLMError("no model configured")


def build_profile(
    query: str,
    llm: Optional[LLMSettings] = None,
    client_factory: Optional[Callable[[str], Any]] = None,
) -> ConstraintProfile:
    """Rules by default. With llm.enabled the model is tried first; any problem falls back to the rules."""
    rules = rules_profile(query)
    if llm is None or not llm.enabled:
        return rules
    try:
        profile = llm_profile(query, llm, client_factory)
    except (LLMError, ValueError) as exc:
        return ConstraintProfile(
            rules.constraints, "rules", f"LLM unavailable or unusable ({exc}); used rules", rules.relations
        )
    if profile.is_empty:
        return ConstraintProfile(
            rules.constraints, "rules", "the model found no structural requirement; used rules", rules.relations
        )
    return profile
