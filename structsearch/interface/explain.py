"""Explanations for ranked results, grounded in the result's own evidence.

template  deterministic. Built only from the evidence lines and the unit's name, so it can never say
          anything the retrieval did not find. This is the default and needs no Ollama.
llm       optional. A local Ollama model gets the numbered evidence lines (and the code excerpt shown to
          the user) and must return {"summary": ..., "cites": [evidence numbers]}. The answer is
          validated: cites must point at real evidence lines; identifiers, dotted/underscored names, backticked
          text and numbers in the summary must appear in the allowed text (evidence, unit id, query, shown
          code); words that overclaim ("vulnerable", "confirmed", "bug", ...) are rejected. Anything that
          fails validation, or an unreachable model, falls back to the template explanation.

Retrieval evidence is syntax- and similarity-based; an explanation never claims a bug or vulnerability.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from structsearch.interface.format import excerpt_lines
from structsearch.llm.ollama import LLMError, LLMSettings, ModelMissingError, OllamaJSON
from structsearch.schemas import CodeUnit, RankedResult

MAX_SUMMARY_CHARS = 500
EXCERPT_LINES = 12
OVERCLAIM = re.compile(
    r"\b(vulnerab\w*|exploit\w*|insecure|unsafe|confirmed?|proven?|definitely|certainly|bugs?|buggy|malicious|attack\w*)\b",
    re.IGNORECASE,
)
_BACKTICKED = re.compile(r"`([^`]+)`")
_CODE_TOKEN = re.compile(r"[A-Za-z_]\w*(?:(?:::|[.:])\w+)+|[A-Za-z]+_\w+")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


@dataclass
class Explanation:
    summary: str
    points: List[str] = field(default_factory=list)  # one grounded sentence per kind of evidence
    source: str = "template"  # "template" or "llm:<model>"
    cited: List[int] = field(default_factory=list)  # 1-based evidence line numbers the explanation relies on
    fallback_reason: Optional[str] = None  # set when the LLM was requested but the template was used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "points": self.points,
            "source": self.source,
            "cited": self.cited,
            "fallback_reason": self.fallback_reason,
        }


# --------------------------------------------------------------------------- template


def _split(line: str, prefix: str) -> Optional[str]:
    return line[len(prefix):].strip() if line.startswith(prefix) else None


def template_explanation(result: RankedResult, unit: CodeUnit) -> Explanation:
    """Deterministic explanation built only from the evidence lines."""
    terms: List[str] = []
    fields: List[str] = []
    semantic: List[str] = []
    matched: List[str] = []
    missed: List[str] = []
    found: List[str] = []
    shared: List[str] = []
    breakdown: Optional[str] = None
    parse_note: Optional[str] = None
    partial_note: Optional[str] = None
    cited: List[int] = []

    for number, line in enumerate(result.evidence, 1):
        rest = _split(line, "term match in ")
        if rest is not None and ":" in rest:
            name, _, words = rest.partition(":")
            fields.append(name.strip())
            terms.extend(w.strip() for w in words.split(",") if w.strip())
        elif (rest := _split(line, "semantic similarity ")) is not None:
            semantic.append(rest)
        elif (rest := _split(line, "structural match: ")) is not None:
            matched.append(re.sub(r"\s*(\[pattern:.*\]|\([^)]*=[^)]*\))\s*$", "", rest))
        elif (rest := _split(line, "structural miss: ")) is not None:
            missed.append(re.sub(r"\s*(\[pattern:.*\]|\([^)]*=[^)]*\))\s*$", "", rest))
        elif (rest := _split(line, "structure found: ")) is not None:
            found.append(rest)
        elif (rest := _split(line, "shared structure: ")) is not None:
            shared.append(rest)
        elif (rest := _split(line, "fusion: ")) is not None:
            breakdown = rest
        elif line.startswith("partial parse"):
            partial_note = line
        elif line.startswith(("file did not parse", "function did not parse")):
            parse_note = line
        else:
            continue
        cited.append(number)

    points: List[str] = []
    if terms:
        unique = list(dict.fromkeys(terms))
        points.append(f"Matches the query terms {', '.join(unique)} (in the {', '.join(dict.fromkeys(fields))}).")
    if semantic:
        points.append(f"Semantically similar to the query ({semantic[0]}).")
    if matched:
        points.append(f"Satisfies the structural requirement: {'; '.join(matched)}.")
    if found:
        points.append(f"Structure found in the code: {'; '.join(dict.fromkeys(found))}.")
    if missed:
        points.append(f"Does not satisfy: {'; '.join(missed)}.")
    if shared:
        points.append(f"Has the same structure as the example: {'; '.join(shared)}.")
    if breakdown:
        points.append(f"Score breakdown: {breakdown}.")
    if partial_note:
        points.append("Part of this function has syntax errors and was skipped; the structural evidence covers the rest.")
    if parse_note:
        points.append("The code does not parse, so this is a text match with no structural evidence.")

    head = f"{unit.unit_id} (lines {unit.start_line}-{unit.end_line})"
    if not points:
        summary = f"{head} was returned, but no detailed evidence was recorded."
    else:
        summary = f"{head}: " + " ".join(points[:2])
    return Explanation(summary, points, "template", cited)


# --------------------------------------------------------------------------- LLM


def llm_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "cites": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["summary", "cites"],
    }


def _excerpt_text(unit: CodeUnit) -> str:
    numbered, _ = excerpt_lines(unit, EXCERPT_LINES)
    return "\n".join(text for _, text in numbered)


def allowed_text(query: str, result: RankedResult, unit: CodeUnit) -> str:
    """Everything a grounded summary may mention."""
    return "\n".join(
        [query, unit.unit_id, unit.name, unit.file_path, f"{unit.start_line}-{unit.end_line}"]
        + list(result.evidence)
        + [_excerpt_text(unit)]
    )


def llm_prompt(query: str, result: RankedResult, unit: CodeUnit) -> str:
    evidence = "\n".join(f"{i}. {line}" for i, line in enumerate(result.evidence, 1)) or "(no evidence recorded)"
    return (
        "You explain why a code-search result was returned. Use ONLY the numbered evidence and the code shown.\n"
        "Write at most two plain sentences. Do not mention anything that is not in the evidence or the code. "
        "Do not call the code buggy, vulnerable or unsafe: the evidence is syntactic and shows similarity only.\n"
        'Return JSON: {"summary": "<sentences>", "cites": [<numbers of the evidence lines you used>]}.\n\n'
        f"Query: {query}\n"
        f"Result: {unit.unit_id} (lines {unit.start_line}-{unit.end_line})\n"
        f"Evidence:\n{evidence}\n\n"
        f"Code (first lines):\n{_excerpt_text(unit)}\n"
    )


def validate_llm_explanation(data: Any, query: str, result: RankedResult, unit: CodeUnit) -> Tuple[str, List[int]]:
    """Return (summary, cites) or raise ValueError saying what was wrong."""
    if not isinstance(data, dict):
        raise ValueError("the answer is not a JSON object")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("missing summary")
    summary = " ".join(summary.split())
    if len(summary) > MAX_SUMMARY_CHARS:
        raise ValueError("summary is too long")
    cites = data.get("cites")
    if not isinstance(cites, list) or not cites:
        raise ValueError("no evidence cited")
    clean: List[int] = []
    for item in cites:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= len(result.evidence):
            raise ValueError(f"cites evidence line {item!r}, which does not exist")
        if item not in clean:
            clean.append(item)
    claim = OVERCLAIM.search(summary)
    if claim:
        raise ValueError(f"overclaiming word '{claim.group(0)}'")

    allowed = allowed_text(query, result, unit)
    tokens = [m.group(1).strip() for m in _BACKTICKED.finditer(summary)]
    tokens += [m.group(0) for m in _CODE_TOKEN.finditer(_BACKTICKED.sub(" ", summary))]
    for token in tokens:
        if token and token not in allowed:
            raise ValueError(f"mentions '{token}', which is not in the evidence or code")
    allowed_numbers = set(_NUMBER.findall(allowed))
    for number in _NUMBER.findall(summary):
        if number not in allowed_numbers:
            raise ValueError(f"mentions the number {number}, which is not in the evidence or code")
    return summary, sorted(clean)


def llm_explanation(
    query: str,
    result: RankedResult,
    unit: CodeUnit,
    settings: LLMSettings,
    client_factory: Optional[Callable[[str], Any]] = None,
) -> Explanation:
    """Ask the model; raises LLMError (unreachable/unusable) or ValueError (failed validation)."""
    factory = client_factory or (lambda model: OllamaJSON(model, settings.host, settings.timeout_seconds))
    models = [settings.model]
    if settings.fallback_model and settings.fallback_model != settings.model:
        models.append(settings.fallback_model)
    last: Optional[LLMError] = None
    for model in models:
        try:
            data = factory(model).generate_json(llm_prompt(query, result, unit), llm_schema())
        except ModelMissingError as exc:
            last = exc
            continue
        summary, cites = validate_llm_explanation(data, query, result, unit)
        base = template_explanation(result, unit)
        return Explanation(summary, base.points, f"llm:{model}", cites)
    raise last or LLMError("no model configured")


def explain_results(
    query: str,
    results: Sequence[RankedResult],
    units_by_id: Mapping[str, CodeUnit],
    method: str = "template",
    llm: Optional[LLMSettings] = None,
    top: int = 3,
    client_factory: Optional[Callable[[str], Any]] = None,
    notify: Optional[Callable[[str], None]] = None,
) -> Dict[str, Explanation]:
    """Explanation per unit_id. method "llm" is tried for the first `top` results only."""
    if method not in ("template", "llm"):
        raise ValueError(f"unknown explanation method '{method}'")
    out: Dict[str, Explanation] = {}
    llm_ok = method == "llm" and llm is not None
    down_reason = ""
    for rank, result in enumerate(results, 1):
        unit = units_by_id[result.unit_id]
        explanation = template_explanation(result, unit)
        if method == "llm" and rank <= max(top, 0):
            if llm is None:
                explanation.fallback_reason = "no LLM settings given; used the template"
            elif not llm_ok:
                explanation.fallback_reason = down_reason
            else:
                try:
                    explanation = llm_explanation(query, result, unit, llm, client_factory)  # type: ignore[arg-type]
                except LLMError as exc:
                    llm_ok = False  # do not wait for the same unreachable server once per result
                    down_reason = explanation.fallback_reason = f"LLM unavailable ({exc}); used the template"
                    if notify:
                        notify(f"note: {explanation.fallback_reason}")
                except ValueError as exc:
                    explanation.fallback_reason = f"LLM answer rejected ({exc}); used the template"
        out[result.unit_id] = explanation
    return out
