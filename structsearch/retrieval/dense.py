"""Dense-only baseline: semantic (embedding) search over the dense index."""
from __future__ import annotations

from typing import List, Mapping, Optional

from structsearch.indexing.dense import DenseIndex, embed_query
from structsearch.indexing.embedder import DenseSettings, Embedder
from structsearch.ingestion.corpus import FailedFile
from structsearch.retrieval.baseline import parse_failure_evidence
from structsearch.schemas import CodeUnit, RankedResult


def dense_search(
    index: DenseIndex,
    embedder: Embedder,
    settings: DenseSettings,
    units_by_id: Mapping[str, CodeUnit],
    query: str,
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Optional[Mapping[str, FailedFile]] = None,
) -> List[RankedResult]:
    """Top-k by cosine similarity. Only dense_score is set; text/structural/graph stay empty.

    Unlike BM25, dense search always returns k results (the least dissimilar ones), so the
    score itself is the only signal of how good a match is.
    """
    query_vector = embed_query(embedder, settings, query)
    results: List[RankedResult] = []
    for unit_id, score in index.search(query_vector, k):
        unit = units_by_id[unit_id]
        evidence = [f"semantic similarity {score:.3f} (cosine, model {index.model})"]
        failure = parse_failure_evidence(unit, failed_by_path)
        if failure:
            evidence.append(failure)
        results.append(
            RankedResult(
                query_id=query_id,
                unit_id=unit_id,
                text_score=0.0,
                structural_score=0.0,
                graph_score=None,
                final_score=score,
                evidence=evidence,
                dense_score=score,
            )
        )
    return results
