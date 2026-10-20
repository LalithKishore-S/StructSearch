"""BM25-only baseline: turns index hits into RankedResults with evidence."""
from __future__ import annotations

from typing import List, Mapping, Optional

from structsearch.indexing.bm25 import BM25Index
from structsearch.ingestion.corpus import FailedFile
from structsearch.schemas import CodeUnit, RankedResult


def parse_failure_evidence(
    unit: CodeUnit, failed_by_path: Optional[Mapping[str, FailedFile]]
) -> Optional[str]:
    """Evidence line for units from files that did not parse (None for normal units)."""
    if unit.parse_status == "ok":
        return None
    if unit.parse_status == "partial":
        lines = ", ".join(str(n) for n in unit.error_lines) or "unknown"
        return f"partial parse: syntax errors at line {lines} were skipped; structural evidence covers the rest"
    if not unit.unit_id.endswith("::<module>"):  # a function recovered by --tolerant that could not be repaired
        return "function did not parse; text match only, no AST evidence"
    failure = (failed_by_path or {}).get(unit.file_path)
    detail = f" - {failure.error}" if failure else ""
    return f"file did not parse{detail}; whole-file match only, no AST evidence"


def bm25_search(
    index: BM25Index,
    units_by_id: Mapping[str, CodeUnit],
    query: str,
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Optional[Mapping[str, FailedFile]] = None,
) -> List[RankedResult]:
    """Top-k BM25 results. Only the text score is set; structural/graph scores stay empty.

    final_score equals text_score here, so later variants (Text+AST, hybrid) can be
    compared against this baseline through the same RankedResult format.
    """
    results: List[RankedResult] = []
    for hit in index.search(query, k):
        unit = units_by_id[hit.unit_id]
        evidence = [
            f"term match in {fld}: {', '.join(terms)}"
            for fld, terms in index.explain(query, hit.unit_id).items()
        ]
        failure = parse_failure_evidence(unit, failed_by_path)
        if failure:
            evidence.append(failure)
        results.append(
            RankedResult(
                query_id=query_id,
                unit_id=hit.unit_id,
                text_score=hit.score,
                structural_score=0.0,
                graph_score=None,
                final_score=hit.score,
                evidence=evidence,
            )
        )
    return results
