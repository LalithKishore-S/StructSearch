"""BM25-only baseline: turns index hits into RankedResults with evidence."""
from __future__ import annotations

from typing import Dict, List, Mapping

from structsearch.indexing.bm25 import BM25Index
from structsearch.ingestion.corpus import FailedFile
from structsearch.schemas import CodeUnit, RankedResult


def bm25_search(
    index: BM25Index,
    units_by_id: Mapping[str, CodeUnit],
    query: str,
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Mapping[str, FailedFile] = None,
) -> List[RankedResult]:
    """Top-k BM25 results. Only the text score is set; structural/graph scores stay empty.

    final_score equals text_score here, so later variants (Text+AST, hybrid) can be
    compared against this baseline through the same RankedResult format.
    """
    failed_by_path = failed_by_path or {}
    results: List[RankedResult] = []
    for hit in index.search(query, k):
        unit = units_by_id[hit.unit_id]
        evidence = [
            f"term match in {fld}: {', '.join(terms)}"
            for fld, terms in index.explain(query, hit.unit_id).items()
        ]
        if unit.parse_status != "ok":
            failure = failed_by_path.get(unit.file_path)
            detail = f" - {failure.error}" if failure else ""
            evidence.append(f"file did not parse{detail}; text match only, no AST evidence")
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
