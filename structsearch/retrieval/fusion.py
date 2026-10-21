"""Score fusion: combine text, dense, structural and graph signals into one ranking.

Each signal gives every unit a raw score. Per query:
  1. a signal is *active* only if it can tell units apart (an all-zero BM25 vector, an empty
     structural profile or a missing graph score carry no information);
  2. scores are normalized to [0, 1] over ALL units of the corpus (so the result does not depend
     on which units happen to be candidates), each signal in the way that fits its scale:
       text, graph   divided by the maximum. BM25 has a true zero (no query term matched), and
                     min-max would wrongly drive the weakest *matching* unit to 0;
       dense         min-max. Cosine similarities of related texts cluster in a narrow band, so
                     only stretching that band separates units;
       structural    used as is: it is already an absolute fraction of satisfied requirements;
  3. weights are renormalized over the active signals, so a missing signal never lowers anyone; a signal
     whose configured weight is 0 is removed (unless every weight is 0, which means equal weights);
  4. final = sum(weight * normalized score), ties broken by unit_id.

Units whose file did not parse have no AST evidence: their structural score is 0, but they keep
their text and dense scores, so they stay findable.

RankedResult fields hold the *normalized* per-signal scores (0..1), which is what final_score
was computed from. The first evidence line shows the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from structsearch.indexing.bm25 import BM25Index
from structsearch.indexing.dense import DenseIndex, embed_query
from structsearch.indexing.embedder import DenseSettings, Embedder
from structsearch.ingestion.corpus import FailedFile
from structsearch.parsing.fragments import FragmentRecord
from structsearch.retrieval.baseline import parse_failure_evidence
from structsearch.retrieval.structural import (
    ConstraintProfile,
    UnitMatch,
    match_evidence,
    match_unit,
)
from structsearch.schemas import PARSEABLE, AstRecord, CodeUnit, RankedResult

SIGNALS = ("text", "dense", "structural", "graph")
EPS = 1e-12


@dataclass
class Signal:
    """Raw scores of one signal for (ideally) every unit."""

    name: str
    scores: Mapping[str, float]
    normalize: Optional[str] = None  # "max", "minmax" or "none"; default depends on the signal name
    evidence: Optional[Callable[[str], List[str]]] = None  # unit_id -> lines, called for top results only


@dataclass
class FusionOutcome:
    results: List[RankedResult]
    active: List[str]  # signals that took part, in SIGNALS order
    weights: Dict[str, float]  # effective weights after renormalization (sum to 1)


DEFAULT_NORMALIZATION = {"text": "max", "dense": "minmax", "structural": "none", "graph": "max"}


def _mode(signal: Signal) -> str:
    mode = signal.normalize or DEFAULT_NORMALIZATION.get(signal.name, "max")
    if mode not in ("max", "minmax", "none"):
        raise ValueError(f"unknown normalization '{mode}' for signal {signal.name}")
    return mode


def is_active(signal: Signal) -> bool:
    """A signal takes part only if it carries information for this query."""
    values = list(signal.scores.values())
    if not values:
        return False
    if _mode(signal) == "minmax":
        return max(values) - min(values) > EPS  # all units equally similar: no information
    return max(values) > EPS


def normalize_scores(signal: Signal, unit_ids: Sequence[str]) -> Dict[str, float]:
    """Per-unit scores in [0, 1]. Units without a score count as 0 (sparse signals) or as the minimum."""
    raw = {u: float(signal.scores.get(u, 0.0)) for u in unit_ids}
    mode = _mode(signal)
    if mode == "none":
        return {u: min(max(v, 0.0), 1.0) for u, v in raw.items()}
    values = list(raw.values())
    if mode == "max":
        high = max(values)
        return {u: (max(v, 0.0) / high if high > EPS else 0.0) for u, v in raw.items()}
    low, high = min(values), max(values)
    if high - low <= EPS:
        return {u: 0.0 for u in unit_ids}
    return {u: (v - low) / (high - low) for u, v in raw.items()}


def effective_weights(active: Sequence[str], weights: Mapping[str, float]) -> Dict[str, float]:
    """Configured weights restricted to the active signals and scaled to sum to 1 (equal if all are 0)."""
    chosen = {name: max(float(weights.get(name, 0.0)), 0.0) for name in active}
    total = sum(chosen.values())
    if not chosen:
        return {}
    if total <= EPS:
        return {name: 1.0 / len(chosen) for name in chosen}
    return {name: value / total for name, value in chosen.items()}


def fuse(
    signals: Sequence[Signal],
    weights: Mapping[str, float],
    unit_ids: Sequence[str],
    k: int = 10,
    query_id: str = "adhoc",
    extra_evidence: Optional[Callable[[str], Optional[str]]] = None,
) -> FusionOutcome:
    unknown = [s.name for s in signals if s.name not in SIGNALS]
    if unknown:
        raise ValueError(f"unknown signal(s): {', '.join(unknown)}")
    # A signal with weight 0 is removed, not just silenced: otherwise, when the weighted signals carry no
    # information, the equal-weights fallback would hand the removed signal full weight. Only when no signal
    # has a positive weight at all (nothing to honour) are all signals kept.
    wanted = [s for s in signals if float(weights.get(s.name, 0.0)) > 0] or list(signals)
    active_signals = [s for s in sorted(wanted, key=lambda s: SIGNALS.index(s.name)) if is_active(s)]
    names = [s.name for s in active_signals]
    eff = effective_weights(names, weights)
    if not active_signals:
        return FusionOutcome([], [], {})

    normalized = {s.name: normalize_scores(s, unit_ids) for s in active_signals}
    ranked: List[Tuple[float, str]] = []
    for unit_id in unit_ids:
        final = sum(eff[n] * normalized[n][unit_id] for n in names)
        if final > EPS:
            ranked.append((final, unit_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    results: List[RankedResult] = []
    for final, unit_id in ranked[: max(k, 0)]:
        parts = " + ".join(f"{n} {normalized[n][unit_id]:.2f}x{eff[n]:.2f}" for n in names)
        evidence = [f"fusion: {parts} = {final:.3f}"]
        for signal in active_signals:
            if signal.evidence:
                evidence.extend(signal.evidence(unit_id))
        if extra_evidence:
            note = extra_evidence(unit_id)
            if note:
                evidence.append(note)
        results.append(
            RankedResult(
                query_id=query_id,
                unit_id=unit_id,
                text_score=normalized["text"][unit_id] if "text" in normalized else 0.0,
                structural_score=normalized["structural"][unit_id] if "structural" in normalized else 0.0,
                graph_score=normalized["graph"][unit_id] if "graph" in normalized else None,
                final_score=final,
                evidence=evidence,
                dense_score=normalized["dense"][unit_id] if "dense" in normalized else None,
            )
        )
    return FusionOutcome(results, names, eff)


# --------------------------------------------------------------------------- assembling signals


def text_signal(index: BM25Index, query: str) -> Signal:
    scores = index.score_all(query)
    by_id = {u: float(scores[i]) for i, u in enumerate(index.unit_ids)}

    def evidence(unit_id: str) -> List[str]:
        return [
            f"term match in {fld}: {', '.join(terms)}"
            for fld, terms in index.explain(query, unit_id).items()
        ]

    return Signal("text", by_id, "max", evidence)


def dense_signal(
    index: DenseIndex, embedder: Embedder, settings: DenseSettings, query: str
) -> Signal:
    vector = embed_query(embedder, settings, query)
    scores = index.score_all(vector)
    by_id = {u: float(scores[i]) for i, u in enumerate(index.unit_ids)}

    def evidence(unit_id: str) -> List[str]:
        return [f"semantic similarity {by_id[unit_id]:.3f} (cosine, model {index.model})"]

    return Signal("dense", by_id, "minmax", evidence)


def structural_signal(
    profile: ConstraintProfile,
    ast_records: Sequence[AstRecord],
    fragments: Optional[Sequence[FragmentRecord]] = None,
) -> Optional[Signal]:
    """None when the query has no structural requirement (the signal then does not exist)."""
    if profile.is_empty:
        return None
    terms_by_id = {f.unit_id: f.terms for f in fragments or ()}
    matches: Dict[str, UnitMatch] = {}
    scores: Dict[str, float] = {}
    for record in ast_records:
        if record.parse_status in PARSEABLE:
            match = match_unit(profile, record.features, terms_by_id.get(record.unit_id))
            matches[record.unit_id] = match
            scores[record.unit_id] = match.score
        else:
            scores[record.unit_id] = 0.0  # no AST evidence for files that did not parse

    def evidence(unit_id: str) -> List[str]:
        match = matches.get(unit_id)
        return match_evidence(match) if match and match.score > 0 else []

    return Signal("structural", scores, "none", evidence)


def graph_signal(
    graph_scores: Optional[Mapping[str, float]], evidence: Optional[Mapping[str, Sequence[str]]] = None
) -> Optional[Signal]:
    """None without scores. `evidence` maps unit_id -> factual lines (e.g. `edge: a -> b (call, line 3)`)."""
    if not graph_scores:
        return None
    lines = (lambda unit_id: list(evidence.get(unit_id, ()))) if evidence else None
    return Signal("graph", dict(graph_scores), "max", lines)


def fused_search(
    query: str,
    units_by_id: Mapping[str, CodeUnit],
    bm25_index: BM25Index,
    weights: Mapping[str, float],
    k: int = 10,
    query_id: str = "adhoc",
    failed_by_path: Optional[Mapping[str, FailedFile]] = None,
    *,
    profile: Optional[ConstraintProfile] = None,
    ast_records: Optional[Sequence[AstRecord]] = None,
    fragments: Optional[Sequence[FragmentRecord]] = None,
    dense: Optional[Tuple[DenseIndex, Embedder, DenseSettings]] = None,
    graph_scores: Optional[Mapping[str, float]] = None,
    graph_evidence: Optional[Mapping[str, Sequence[str]]] = None,
) -> FusionOutcome:
    """BM25 plus any of: structural profile, dense index, graph scores. Absent inputs are simply not used."""
    signals: List[Signal] = [text_signal(bm25_index, query)]
    if dense is not None:
        signals.append(dense_signal(dense[0], dense[1], dense[2], query))
    if profile is not None and ast_records is not None:
        structural = structural_signal(profile, ast_records, fragments)
        if structural is not None:
            signals.append(structural)
    graph = graph_signal(graph_scores, graph_evidence)
    if graph is not None:
        signals.append(graph)

    def parse_note(unit_id: str) -> Optional[str]:
        return parse_failure_evidence(units_by_id[unit_id], failed_by_path)

    unit_ids = [u for u in bm25_index.unit_ids if u in units_by_id]
    return fuse(signals, weights, unit_ids, k, query_id, parse_note)
