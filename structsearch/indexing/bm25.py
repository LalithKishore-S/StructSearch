"""Multi-field BM25 index over TextRecords.

Four fields are indexed separately with BM25 Okapi (rank-bm25, Lucene-style idf):
  name         qualified function name (Class.method)
  identifiers  names used inside the code
  doc          docstring and comments
  code         every word in the source (keywords and string-literal words included)
The score is the weighted sum of the per-field BM25 scores, so a term in the function
name counts more than the same term somewhere in the body. Weights live in the config.

Persistence: tokenized fields are saved as JSON and the BM25 statistics are rebuilt on
load (deterministic, no pickle), so a reloaded index gives identical scores.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
from rank_bm25 import BM25Okapi

from structsearch.indexing.tokenizer import tokenize_query, tokenize_text, tokenize_words
from structsearch.schemas import TextRecord

class _BM25(BM25Okapi):
    """BM25 Okapi with Lucene-style idf, log(1 + (N - n + 0.5) / (n + 0.5)).

    The idf in rank-bm25's BM25Okapi is zero for a term found in exactly half of the
    documents and negative above that (then floored), so tiny corpora score 0 for real
    matches. The Lucene form is always positive and is the one Elasticsearch uses.
    """

    def _calc_idf(self, nd):
        for word, freq in nd.items():
            self.idf[word] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
        self.average_idf = sum(self.idf.values()) / len(self.idf) if self.idf else 0.0


FIELDS = ("name", "identifiers", "doc", "code")
DEFAULT_FIELD_WEIGHTS = {"name": 3.0, "identifiers": 2.0, "doc": 1.5, "code": 1.0}
INDEX_VERSION = 1


@dataclass
class Hit:
    unit_id: str
    score: float
    field_scores: Dict[str, float] = field(default_factory=dict)  # weighted, sums to score


def record_fields(record: TextRecord) -> Dict[str, List[str]]:
    return {
        "name": tokenize_words([record.name]),
        "identifiers": tokenize_words(record.identifiers),
        "doc": tokenize_text(record.docstring_comments),
        "code": tokenize_words(record.code_tokens),
    }


class BM25Index:
    def __init__(
        self,
        unit_ids: Sequence[str],
        field_tokens: Dict[str, List[List[str]]],
        field_weights: Optional[Dict[str, float]] = None,
        k1: float = 1.5,
        b: float = 0.75,
        fingerprint: str = "",
    ):
        self.unit_ids: List[str] = list(unit_ids)
        self.field_tokens = {f: field_tokens[f] for f in FIELDS}
        self.field_weights = {**DEFAULT_FIELD_WEIGHTS, **(field_weights or {})}
        self.k1 = k1
        self.b = b
        self.fingerprint = fingerprint
        self._pos = {uid: i for i, uid in enumerate(self.unit_ids)}
        self._bm25: Dict[str, _BM25] = {}
        for name in FIELDS:
            docs = self.field_tokens[name]
            # rank-bm25 divides by the average document length: skip empty fields
            if docs and any(docs):
                self._bm25[name] = _BM25(docs, k1=k1, b=b)

    # ---- building ----
    @classmethod
    def build(
        cls,
        records: Sequence[TextRecord],
        field_weights: Optional[Dict[str, float]] = None,
        k1: float = 1.5,
        b: float = 0.75,
        fingerprint: str = "",
    ) -> "BM25Index":
        field_tokens: Dict[str, List[List[str]]] = {f: [] for f in FIELDS}
        for record in records:
            fields = record_fields(record)
            for name in FIELDS:
                field_tokens[name].append(fields[name])
        return cls([r.unit_id for r in records], field_tokens, field_weights, k1, b, fingerprint)

    # ---- querying ----
    def _field_scores(self, query_tokens: List[str]) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}
        for name, bm25 in self._bm25.items():
            weight = self.field_weights.get(name, 0.0)
            if weight:
                out[name] = weight * np.asarray(bm25.get_scores(query_tokens), dtype=float)
        return out

    def score_all(self, query: str) -> np.ndarray:
        """Score of every unit, aligned with self.unit_ids (used later by fusion)."""
        total = np.zeros(len(self.unit_ids))
        tokens = tokenize_query(query)
        if not tokens:
            return total
        for scores in self._field_scores(tokens).values():
            total += scores
        return total

    def search(self, query: str, k: int = 10) -> List[Hit]:
        """Top-k units with score > 0. Ties are broken by unit_id for determinism."""
        tokens = tokenize_query(query)
        if not tokens or not self.unit_ids:
            return []
        per_field = self._field_scores(tokens)
        total = np.zeros(len(self.unit_ids))
        for scores in per_field.values():
            total += scores
        order = sorted(range(len(total)), key=lambda i: (-total[i], self.unit_ids[i]))
        hits: List[Hit] = []
        for i in order[:k]:
            if total[i] <= 0:
                break
            hits.append(
                Hit(
                    unit_id=self.unit_ids[i],
                    score=float(total[i]),
                    field_scores={f: float(s[i]) for f, s in per_field.items()},
                )
            )
        return hits

    def explain(self, query: str, unit_id: str) -> Dict[str, List[str]]:
        """Query terms that occur in each field of the unit (evidence for display)."""
        tokens = set(tokenize_query(query))
        i = self._pos[unit_id]
        matched = {}
        for name in FIELDS:
            terms = sorted(tokens & set(self.field_tokens[name][i]))
            if terms:
                matched[name] = terms
        return matched

    # ---- persistence ----
    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "k1": self.k1,
            "b": self.b,
            "field_weights": self.field_weights,
            "fingerprint": self.fingerprint,
            "unit_ids": self.unit_ids,
            "fields": self.field_tokens,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def load(cls, path: Union[str, Path]) -> "BM25Index":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("version") != INDEX_VERSION:
            raise ValueError(f"unsupported index version: {payload.get('version')}")
        return cls(
            payload["unit_ids"],
            payload["fields"],
            payload["field_weights"],
            payload["k1"],
            payload["b"],
            payload.get("fingerprint", ""),
        )
