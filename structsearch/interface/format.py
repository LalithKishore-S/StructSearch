"""Render ranked results as readable text or JSON (ASCII only, safe for any terminal)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from structsearch.schemas import CodeUnit, RankedResult, status_flag

MAX_LINE_WIDTH = 110


def excerpt_lines(unit: CodeUnit, max_lines: int) -> Tuple[List[Tuple[int, str]], int]:
    """First max_lines lines of the unit with their real file line numbers, plus how many were cut."""
    lines = unit.source_text.split("\n")
    shown = lines[: max(max_lines, 0)]
    numbered = [(unit.start_line + i, text) for i, text in enumerate(shown)]
    return numbered, len(lines) - len(shown)


def _clip(text: str) -> str:
    text = text.rstrip()
    return text if len(text) <= MAX_LINE_WIDTH else text[: MAX_LINE_WIDTH - 3] + "..."


def format_results(
    query: str,
    results: List[RankedResult],
    units_by_id: Mapping[str, CodeUnit],
    total_units: int,
    max_lines: int = 8,
    mode: str = "bm25",
    explanations: Optional[Mapping[str, Any]] = None,
) -> str:
    header = f'Query: "{query}"   mode: {mode}   {len(results)} result(s) from {total_units} units'
    if not results:
        return header + "\n\nNo results."
    out = [header, ""]
    for rank, res in enumerate(results, 1):
        unit = units_by_id[res.unit_id]
        flag = status_flag(unit)
        out.append(f"{rank:>2}. {res.unit_id}   score {res.final_score:.3f}{flag}")
        out.append(f"    {unit.file_path}:{unit.start_line}-{unit.end_line}")
        for item in res.evidence:
            out.append(f"    - {item}")
        explanation = (explanations or {}).get(res.unit_id)
        if explanation is not None:
            tag = "" if explanation.source == "template" else f"  [{explanation.source}, cites {explanation.cited}]"
            out.append(f"    why: {_clip(explanation.summary)}{tag}")
        numbered, hidden = excerpt_lines(unit, max_lines)
        width = len(str(unit.end_line))
        for lineno, text in numbered:
            out.append(f"    {lineno:>{width}} | {_clip(text)}")
        if hidden:
            out.append(f"    {'':>{width}} | ... (+{hidden} more lines)")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def result_to_dict(
    res: RankedResult, unit: CodeUnit, max_lines: int = 8, explanation: Any = None
) -> Dict[str, Any]:
    numbered, hidden = excerpt_lines(unit, max_lines)
    data = res.to_dict()
    data.update(
        {
            "name": unit.name,
            "file_path": unit.file_path,
            "start_line": unit.start_line,
            "end_line": unit.end_line,
            "parse_status": unit.parse_status,
            "excerpt": "\n".join(text for _, text in numbered),
            "excerpt_truncated_lines": hidden,
        }
    )
    if explanation is not None:
        data["explanation"] = explanation.to_dict()
    return data
