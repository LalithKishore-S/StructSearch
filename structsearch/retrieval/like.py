"""Query by example: rank functions by structural similarity to a pasted snippet.

Every function is a "document" whose words are its fragment terms (parsing/fragments.py:
node kinds, parent-child pairs, 3-chains, contains and before relations). The snippet is turned
into the same kind of terms and scored with BM25. Rare shared relations (a Try inside a For)
count more than common ones (a Return), exactly as rare words do in text search.

BM25 scores are unbounded and only comparable within one query; fusion (Step 6) normalizes them.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from structsearch.indexing.bm25 import _BM25
from structsearch.ingestion.corpus import FailedFile
from structsearch.parsing.fragments import PARSE_OK, FragmentRecord, describe_term, split_term
from structsearch.retrieval.baseline import parse_failure_evidence
from structsearch.schemas import CodeUnit, RankedResult

K1 = 1.5
B = 0.75
MAX_EVIDENCE_TERMS = 5
# 'u:' alone (the function merely contains an If) is too weak to quote as evidence. The weights make
# ordering/containment relations win ties against equally rare parent-child pairs.
_EVIDENCE_WEIGHT = {"ord": 1.3, "ch3": 1.1, "ad": 1.0, "pc": 0.9}


class FragmentIndex:
    """BM25 over fragment terms. Built from FragmentRecords (cheap; nothing is pickled)."""

    def __init__(self, records: Sequence[FragmentRecord]):
        self.records = [r for r in records if r.parse_status == PARSE_OK and r.terms]
        corpus = [[t for t, n in r.terms.items() for _ in range(max(n, 1))] for r in self.records]
        self._bm25 = _BM25(corpus, k1=K1, b=B) if corpus else None
        self._sets = [set(r.terms) for r in self.records]

    def __len__(self) -> int:
        return len(self.records)

    def scores(self, query_terms: Sequence[str]) -> List[float]:
        if self._bm25 is None:
            return []
        return [float(x) for x in self._bm25.get_scores(list(query_terms))]

    def idf(self, term: str) -> float:
        return float(self._bm25.idf.get(term, 0.0)) if self._bm25 is not None else 0.0

    def shared_terms(self, doc_index: int, query_terms: Sequence[str]) -> List[str]:
        """Most informative query terms the document also has (rarest first)."""
        shared = [t for t in query_terms if t in self._sets[doc_index] and split_term(t)[0] in _EVIDENCE_WEIGHT]
        weight = lambda t: self.idf(t) * _EVIDENCE_WEIGHT[split_term(t)[0]]  # noqa: E731
        return sorted(shared, key=lambda t: (-weight(t), t))[:MAX_EVIDENCE_TERMS]


def like_search(
    index: FragmentIndex,
    units_by_id: Mapping[str, CodeUnit],
    snippet_term_counts: Mapping[str, int],
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Optional[Mapping[str, FailedFile]] = None,
) -> List[RankedResult]:
    """Top-k functions most similar in structure to the snippet (score > 0 only)."""
    query_terms = sorted(snippet_term_counts)  # each distinct term once
    scores = index.scores(query_terms)
    order = sorted(
        (i for i, score in enumerate(scores) if score > 0 and index.records[i].unit_id in units_by_id),
        key=lambda i: (-scores[i], index.records[i].unit_id),
    )
    results: List[RankedResult] = []
    for i in order[: max(k, 0)]:
        record = index.records[i]
        evidence = ["shared structure: " + describe_term(t) for t in index.shared_terms(i, query_terms)]
        failure = parse_failure_evidence(units_by_id[record.unit_id], failed_by_path)
        if failure:
            evidence.append(failure)
        results.append(
            RankedResult(
                query_id=query_id,
                unit_id=record.unit_id,
                text_score=0.0,
                structural_score=scores[i],
                graph_score=None,
                final_score=scores[i],
                evidence=evidence,
            )
        )
    return results
