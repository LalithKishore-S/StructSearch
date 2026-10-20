"""Search service: one place that turns a SearchRequest into ranked results.

The command line and the optional Streamlit app both call run_search, so every mode behaves the
same everywhere. Status messages go through a `notify` callback (stderr in the CLI, a list in the
app); failures raise SearchError with the exit code the CLI should use (2 = bad input).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from structsearch.indexing.builder import FAILED_FILE, ensure_index
from structsearch.indexing.dense import ensure_dense_index
from structsearch.indexing.embedder import DenseSettings, make_embedder
from structsearch.indexing.tokenizer import tokenize_query
from structsearch.ingestion.corpus import load_failed
from structsearch.llm import LLMSettings
from structsearch.parsing import ensure_ast_records, ensure_fragment_records, snippet_terms
from structsearch.retrieval.baseline import bm25_search
from structsearch.retrieval.dense import dense_search
from structsearch.retrieval.fusion import SIGNALS, fused_search
from structsearch.retrieval.like import FragmentIndex, like_search
from structsearch.retrieval.patterns import PatternError, parse_pattern
from structsearch.retrieval.structural import ConstraintProfile, build_profile, structural_search
from structsearch.schemas import CodeUnit, RankedResult

MODES = ("bm25", "dense", "structural", "like", "text_ast", "hybrid")
FUSED_MODES = ("text_ast", "hybrid")

Notify = Callable[[str], None]
Progress = Callable[[int, int], None]


class SearchError(Exception):
    """A request that cannot be served; `code` is the CLI exit code."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def _silent(message: str) -> None:
    pass


@dataclass
class SearchRequest:
    query: str
    mode: str = "bm25"
    k: int = 10
    corpus: str = "."
    index_dir: str = ".structsearch_index"
    skip_failed: bool = False
    tolerant: bool = False  # recover functions from files that do not parse (needs tree-sitter)
    rebuild: bool = False
    query_id: str = "adhoc"
    embedder: Optional[str] = None  # "ollama" or "hashing"; None = config
    model: Optional[str] = None  # embedding model; None = config
    llm: LLMSettings = field(default_factory=LLMSettings)  # query mapper settings
    patterns: List[str] = field(default_factory=list)
    weights: List[str] = field(default_factory=list)  # "signal=value" overrides


@dataclass
class SearchResponse:
    request: SearchRequest
    results: List[RankedResult]
    units_by_id: Dict[str, CodeUnit]
    total_units: int
    extra: Dict[str, Any] = field(default_factory=dict)  # profile, fusion, embedding_model


# --------------------------------------------------------------------------- building blocks


def load_corpus(corpus: str, index_dir: str, skip_failed: bool, rebuild: bool, notify: Notify = _silent,
                tolerant: bool = False):
    path = Path(corpus)
    if not path.exists():
        raise SearchError(f"corpus path not found: {corpus}")
    units, index, reason = ensure_index(path, index_dir, include_failed=not skip_failed, rebuild=rebuild, tolerant=tolerant)
    if reason:
        notify(f"index built ({reason}): {len(units)} units -> {index_dir}")
    return units, index


def prepare_dense(cfg, units, index_dir, embedder, model, rebuild, notify: Notify = _silent, progress=None):
    """(dense_index, embedder, settings), building or refreshing the dense index."""
    settings = DenseSettings.from_config(cfg, backend=embedder, model=model)
    emb = make_embedder(settings)
    if settings.backend == "hashing":
        notify("note: the hashing embedder is lexical, not semantic (tests and offline demos only)")
    index, reason = ensure_dense_index(units, index_dir, emb, settings, rebuild=rebuild, progress=progress)
    if reason:
        notify(f"dense index built ({reason}): {len(index.unit_ids)} units, {index.dim} dims, model {index.model}")
    return index, emb, settings


def make_profile(query: str, llm: LLMSettings, patterns: List[str], notify: Notify = _silent) -> ConstraintProfile:
    """Structural profile from the query plus explicit patterns. Raises SearchError for a bad pattern."""
    try:
        explicit = [parse_pattern(text) for text in patterns]
    except PatternError as exc:
        raise SearchError(f"bad --pattern: {exc}") from exc
    profile = build_profile(query, llm).with_relations(explicit)
    if profile.fallback_reason:
        notify(f"note: {profile.fallback_reason}")
    return profile


def structure_inputs(req: SearchRequest, units, notify: Notify = _silent):
    """(profile, ast records, fragment records or None)."""
    profile = make_profile(req.query, req.llm, req.patterns, notify)
    records, reason = ensure_ast_records(units, req.index_dir)
    if reason:
        notify(f"AST features extracted ({reason}): {len(records)} units")
    fragments = None
    if profile.relations:
        fragments, reason = ensure_fragment_records(units, req.index_dir)
        if reason:
            notify(f"fragments extracted ({reason}): {len(fragments)} units")
    return profile, records, fragments


def fusion_weights(mode: str, cfg: Mapping[str, Any], overrides: List[str]) -> Dict[str, float]:
    """Config weights for the mode with "signal=value" overrides applied. Raises SearchError."""
    weights = dict(cfg["hybrid_weights"] if mode == "hybrid" else cfg["weights"])
    for item in overrides:
        name, sep, raw = item.partition("=")
        name = name.strip()
        if not sep or name not in SIGNALS:
            raise SearchError(f"--weight must look like SIGNAL=VALUE with SIGNAL one of {', '.join(SIGNALS)}: '{item}'")
        try:
            value = float(raw)
        except ValueError:
            raise SearchError(f"--weight {name}: '{raw}' is not a number") from None
        if not value >= 0 or value == float("inf"):
            raise SearchError(f"--weight {name} must be a finite number >= 0")
        weights[name] = value
    return weights


def read_snippet(query: str) -> str:
    """A snippet query is code, or '@path' pointing at a file with code."""
    if not query.startswith("@"):
        return query
    try:
        return Path(query[1:]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SearchError(f"cannot read snippet file {query[1:]}: {exc}") from exc


# --------------------------------------------------------------------------- the search itself


def run_search(
    req: SearchRequest,
    cfg: Mapping[str, Any],
    notify: Notify = _silent,
    progress: Optional[Progress] = None,
) -> SearchResponse:
    if req.mode not in MODES:
        raise SearchError(f"unknown mode '{req.mode}' (choose from {', '.join(MODES)})")
    if req.k < 1:
        raise SearchError("-k must be at least 1")
    units, bm25_index = load_corpus(req.corpus, req.index_dir, req.skip_failed, req.rebuild, notify, req.tolerant)
    units_by_id = {u.unit_id: u for u in units}
    failed_by_path = {f.rel_path: f for f in load_failed(Path(req.index_dir) / FAILED_FILE)}
    extra: Dict[str, Any] = {}

    def no_terms_note() -> None:
        if not tokenize_query(req.query):
            notify("note: the query has no searchable terms after removing stopwords")

    if req.mode == "structural":
        profile, records, fragments = structure_inputs(req, units, notify)
        if profile.is_empty:
            notify("note: no structural requirements found in the query; nothing to rank (try --mode bm25)")
        results = structural_search(profile, units_by_id, records, req.k, req.query_id, failed_by_path, fragments)
        extra["profile"] = profile.to_dict()
        notify(f"structural profile ({profile.source}): {profile.describe()}")
    elif req.mode in FUSED_MODES:
        profile, records, fragments = structure_inputs(req, units, notify)
        weights = fusion_weights(req.mode, cfg, req.weights)
        dense = None
        if req.mode == "hybrid":
            dense = prepare_dense(cfg, units, req.index_dir, req.embedder, req.model, req.rebuild, notify, progress)
        no_terms_note()
        outcome = fused_search(
            req.query, units_by_id, bm25_index, weights, req.k, req.query_id, failed_by_path,
            profile=profile, ast_records=records, fragments=fragments, dense=dense,
        )
        results = outcome.results
        if profile.is_empty:
            notify("note: no structural requirements found in the query; ranking without the structure signal")
        else:
            notify(f"structural profile ({profile.source}): {profile.describe()}")
        notify("fusion signals: " + ", ".join(f"{n} {w:.2f}" for n, w in outcome.weights.items()))
        extra["profile"] = profile.to_dict()
        extra["fusion"] = {"signals": outcome.active, "weights": {n: round(w, 6) for n, w in outcome.weights.items()}}
        if dense is not None:
            extra["embedding_model"] = dense[0].model
    elif req.mode == "like":
        try:
            wanted = snippet_terms(read_snippet(req.query))
        except ValueError as exc:
            raise SearchError(str(exc)) from exc
        fragments, reason = ensure_fragment_records(units, req.index_dir)
        if reason:
            notify(f"fragments extracted ({reason}): {len(fragments)} units")
        results = like_search(FragmentIndex(fragments), units_by_id, wanted, req.k, req.query_id, failed_by_path)
    elif req.mode == "dense":
        dense_index, embedder, settings = prepare_dense(
            cfg, units, req.index_dir, req.embedder, req.model, req.rebuild, notify, progress
        )
        results = dense_search(
            dense_index, embedder, settings, units_by_id, req.query, req.k, req.query_id, failed_by_path
        )
        extra["embedding_model"] = dense_index.model
    else:
        no_terms_note()
        results = bm25_search(bm25_index, units_by_id, req.query, req.k, req.query_id, failed_by_path)

    return SearchResponse(req, results, units_by_id, len(units), extra)
