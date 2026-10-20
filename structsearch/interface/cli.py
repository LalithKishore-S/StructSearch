"""StructSearch command line.

  python -m structsearch index [CORPUS] [--dense]       build/refresh the index(es)
  python -m structsearch search "read file" -k 5        BM25 search (builds the index if needed)
  python -m structsearch search "check credentials" --mode dense   semantic search (needs Ollama)
  python -m structsearch features [UNIT]                show the AST features of one unit (or a table of all)
  python -m structsearch search "recursive traversal" --mode structural   AST-constraint search
  python -m structsearch search "..." --mode structural --pattern "For//Try"   add an explicit pattern
  python -m structsearch search "@snippet.py" --mode like               structure similar to a code snippet
  python -m structsearch profile "read file without error handling"       show the constraints a query maps to
  python -m structsearch fragments UNIT                                  show a unit's structure relations

Status messages go to stderr so that --json output on stdout stays clean.
Exit codes: 0 ok, 2 bad argument or missing corpus, 3 embedding backend problem.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Callable, List, Optional

from structsearch.config import load_config
from structsearch.indexing.builder import FAILED_FILE, ensure_index
from structsearch.indexing.dense import ensure_dense_index
from structsearch.indexing.embedder import DenseSettings, EmbeddingError, make_embedder
from structsearch.indexing.tokenizer import tokenize_query
from structsearch.ingestion.corpus import load_failed
from structsearch.interface.format import format_results, result_to_dict
from structsearch.llm import LLMSettings
from structsearch.parsing import (
    FEATURE_NAMES,
    describe_term,
    ensure_ast_records,
    ensure_fragment_records,
    node_type_counts,
    snippet_terms,
)
from structsearch.retrieval.baseline import bm25_search
from structsearch.retrieval.dense import dense_search
from structsearch.retrieval.like import FragmentIndex, like_search
from structsearch.retrieval.patterns import PatternError, parse_pattern
from structsearch.retrieval.structural import build_profile, structural_search

MODES = ("bm25", "dense", "structural", "like")  # text_ast and hybrid are added in later steps


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _add_dense_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedder",
        choices=("ollama", "hashing"),
        default=None,
        help="dense backend (default from config; 'hashing' is lexical, for tests/offline demos)",
    )
    parser.add_argument("--model", default=None, help="Ollama embedding model (default from config)")


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="map the query to structural constraints with a local Ollama model (falls back to rules)",
    )
    parser.add_argument("--llm-model", default=None, help="Ollama model for --use-llm (default from config)")


def _add_pattern_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        metavar="PATTERN",
        help='structural pattern, repeatable and ANDed, e.g. "For//Try", "!With//Call:open", "If=>Call:execute"',
    )


def _llm_settings(args, cfg) -> LLMSettings:
    enabled = True if getattr(args, "use_llm", False) else None  # None keeps the config value
    return LLMSettings.from_config(cfg, model=getattr(args, "llm_model", None), enabled=enabled)


def _build_parser(cfg) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="structsearch", description="Structure-aware code search.")
    sub = parser.add_subparsers(dest="command", required=True)

    index_p = sub.add_parser("index", help="build or refresh the index")
    index_p.add_argument("corpus", nargs="?", default=cfg["corpus_path"], help="folder (or file) to index")
    index_p.add_argument("--index-dir", default=cfg["index_dir"])
    index_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    index_p.add_argument("--rebuild", action="store_true", help="force a rebuild")
    index_p.add_argument("--dense", action="store_true", help="also build the dense (embedding) index")
    _add_dense_args(index_p)

    search_p = sub.add_parser("search", help="search the indexed code")
    search_p.add_argument("query")
    search_p.add_argument("-k", type=int, default=cfg["top_k"], help="number of results")
    search_p.add_argument("--mode", choices=MODES, default="bm25")
    search_p.add_argument("--corpus", default=cfg["corpus_path"], help="folder (or file) to search")
    search_p.add_argument("--index-dir", default=cfg["index_dir"])
    search_p.add_argument("--lines", type=int, default=8, help="excerpt lines per result")
    search_p.add_argument("--json", action="store_true", help="machine-readable output")
    search_p.add_argument("--rebuild", action="store_true", help="force an index rebuild first")
    search_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    search_p.add_argument("--query-id", default="adhoc", help="id stored in the result records")
    _add_dense_args(search_p)
    _add_llm_args(search_p)
    _add_pattern_arg(search_p)

    prof_p = sub.add_parser("profile", help="show the structural constraints a query maps to")
    prof_p.add_argument("query")
    prof_p.add_argument("--json", action="store_true")
    _add_llm_args(prof_p)
    _add_pattern_arg(prof_p)

    frag_p = sub.add_parser("fragments", help="show the structure relations (fragment terms) of a unit")
    frag_p.add_argument("unit", help="unit id or part of one, e.g. db.py::find_user_unsafe")
    frag_p.add_argument("--corpus", default=cfg["corpus_path"])
    frag_p.add_argument("--index-dir", default=cfg["index_dir"])
    frag_p.add_argument("--kind", choices=("u", "pc", "ch3", "ad", "ord"), default=None, help="only one relation kind")
    frag_p.add_argument("--json", action="store_true")
    frag_p.add_argument("--skip-failed", action="store_true")
    frag_p.add_argument("--rebuild", action="store_true")

    feat_p = sub.add_parser("features", help="show AST features of a unit (or a table of all units)")
    feat_p.add_argument("unit", nargs="?", help="unit id or part of one, e.g. trees.py::factorial")
    feat_p.add_argument("--corpus", default=cfg["corpus_path"])
    feat_p.add_argument("--index-dir", default=cfg["index_dir"])
    feat_p.add_argument("--json", action="store_true")
    feat_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    feat_p.add_argument("--rebuild", action="store_true", help="force an index rebuild first")
    return parser


TABLE_COLUMNS = (
    ("if", "if_count"), ("for", "for_count"), ("while", "while_count"), ("try", "try_count"),
    ("call", "call_count"), ("ret", "return_count"), ("depth", "max_depth"), ("self", "self_call"),
)


def _features_command(args) -> int:
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    records, reason = ensure_ast_records(units, args.index_dir)
    if reason:
        _err(f"AST features extracted ({reason}): {len(records)} units")
    pairs = list(zip(units, records))
    if args.unit:
        chosen = [p for p in pairs if p[0].unit_id == args.unit] or [p for p in pairs if args.unit in p[0].unit_id]
        if not chosen:
            _err(f"error: no unit matches '{args.unit}'")
            return 2
        pairs = chosen

    if args.json:
        payload = [
            {"unit_id": u.unit_id, "parse_status": r.parse_status, "features": r.features} for u, r in pairs
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not args.unit:
        width = max((len(u.unit_id) for u, _ in pairs), default=4)
        print(f"{'unit':<{width}}  " + " ".join(f"{label:>5}" for label, _ in TABLE_COLUMNS))
        for unit, rec in pairs:
            if rec.parse_status != "ok":
                print(f"{unit.unit_id:<{width}}  (file did not parse: no AST features)")
                continue
            cells = " ".join(f"{int(rec.features[name]):>5}" for _, name in TABLE_COLUMNS)
            print(f"{unit.unit_id:<{width}}  {cells}")
        return 0

    for unit, rec in pairs[:10]:
        print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]")
        if rec.parse_status != "ok":
            print("  file did not parse: no AST features")
            continue
        for name in FEATURE_NAMES:
            if rec.features.get(name):
                print(f"  {name:<24}{rec.features[name]:g}")
        types = sorted(node_type_counts(rec).items(), key=lambda kv: (-kv[1], kv[0]))
        print("  node types: " + ", ".join(f"{t}={int(n)}" for t, n in types))
        print()
    if len(pairs) > 10:
        _err(f"note: {len(pairs) - 10} more matching units not shown; use a longer unit id")
    return 0


def _load(args, corpus: str):
    corpus_path = Path(corpus)
    if not corpus_path.exists():
        _err(f"error: corpus path not found: {corpus}")
        return None
    units, index, reason = ensure_index(
        corpus_path,
        args.index_dir,
        include_failed=not args.skip_failed,
        rebuild=args.rebuild,
    )
    if reason:
        _err(f"index built ({reason}): {len(units)} units -> {args.index_dir}")
    return units, index


def _progress_printer() -> Callable[[int, int], None]:
    state = {"last": -1}

    def report(done: int, total: int) -> None:
        percent = 100 * done // max(total, 1)
        if done == total or percent // 10 > state["last"] // 10:
            _err(f"  embedding units: {done}/{total}")
            state["last"] = percent

    return report


def _dense(args, cfg, units):
    """Return (dense_index, embedder, settings), building or refreshing the dense index."""
    settings = DenseSettings.from_config(cfg, backend=args.embedder, model=args.model)
    embedder = make_embedder(settings)
    if settings.backend == "hashing":
        _err("note: the hashing embedder is lexical, not semantic (tests and offline demos only)")
    index, reason = ensure_dense_index(
        units, args.index_dir, embedder, settings, rebuild=args.rebuild, progress=_progress_printer()
    )
    if reason:
        _err(f"dense index built ({reason}): {len(index.unit_ids)} units, {index.dim} dims, model {index.model}")
    return index, embedder, settings


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    args = _build_parser(cfg).parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    try:
        return _run(args, cfg)
    except EmbeddingError as exc:
        _err(f"error: {exc}")
        return 3


def _profile_for(args, cfg):
    """Profile from the query plus any --pattern flags. Raises PatternError for a bad flag."""
    explicit = [parse_pattern(text) for text in getattr(args, "pattern", [])]
    profile = build_profile(args.query, _llm_settings(args, cfg)).with_relations(explicit)
    if profile.fallback_reason:
        _err(f"note: {profile.fallback_reason}")
    return profile


def _profile_command(args, cfg) -> int:
    try:
        profile = _profile_for(args, cfg)
    except PatternError as exc:
        _err(f"error: bad --pattern: {exc}")
        return 2
    if args.json:
        print(json.dumps({"query": args.query, **profile.to_dict()}, indent=2))
        return 0
    print(f"mapper: {profile.source}")
    if profile.is_empty:
        print("no structural requirements found in the query")
    for c in profile.constraints:
        op = f"{c.op} {c.value:g}" if c.op in ("at_least", "at_most") else c.op
        print(f"  {op:<12} {'+'.join(c.features):<50} {c.reason}")
    for r in profile.relations:
        print(f"  {'pattern':<12} {r.text:<50} {r.reason if r.reason != r.text else ''}".rstrip())
    return 0


def _fragments_command(args) -> int:
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    records, reason = ensure_fragment_records(units, args.index_dir)
    if reason:
        _err(f"fragments extracted ({reason}): {len(records)} units")
    pairs = list(zip(units, records))
    chosen = [p for p in pairs if p[0].unit_id == args.unit] or [p for p in pairs if args.unit in p[0].unit_id]
    if not chosen:
        _err(f"error: no unit matches '{args.unit}'")
        return 2
    chosen = chosen[:5]
    if args.json:
        print(json.dumps([{"unit_id": u.unit_id, "terms": {
            t: n for t, n in r.terms.items() if args.kind in (None, t.split(":", 1)[0])}} for u, r in chosen], indent=2))
        return 0
    for unit, rec in chosen:
        print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]")
        if rec.parse_status != "ok":
            print("  file did not parse: no fragments")
            continue
        for kind in ("ord", "ad", "ch3", "pc", "u"):
            if args.kind not in (None, kind):
                continue
            terms = sorted(t for t in rec.terms if t.split(":", 1)[0] == kind)
            print(f"  {kind} ({len(terms)}):")
            for term in terms[:25]:
                print(f"    {term[len(kind) + 1:]:<48} {describe_term(term)}")
            if len(terms) > 25:
                print(f"    ... +{len(terms) - 25} more (use --json)")
        print()
    return 0


def _run(args, cfg) -> int:
    if args.command == "features":
        return _features_command(args)
    if args.command == "profile":
        return _profile_command(args, cfg)
    if args.command == "fragments":
        return _fragments_command(args)

    if args.command == "index":
        loaded = _load(args, args.corpus)
        if loaded is None:
            return 2
        units, _ = loaded
        failed = load_failed(Path(args.index_dir) / FAILED_FILE)
        print(f"units indexed : {len(units)}")
        print(f"failed files  : {len(failed)}")
        for item in failed:
            where = f" (line {item.line})" if item.line else ""
            print(f"  - {item.rel_path}{where}: {item.error}")
        if args.dense:
            dense_index, _, _ = _dense(args, cfg, units)
            print(f"dense vectors : {len(dense_index.unit_ids)} x {dense_index.dim} (model {dense_index.model})")
        print(f"index folder  : {args.index_dir}")
        return 0

    # search
    if args.k < 1:
        _err("error: -k must be at least 1")
        return 2
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, bm25_index = loaded
    units_by_id = {u.unit_id: u for u in units}
    failed_by_path = {f.rel_path: f for f in load_failed(Path(args.index_dir) / FAILED_FILE)}

    extra = {}
    if args.mode == "structural":
        try:
            profile = _profile_for(args, cfg)
        except PatternError as exc:
            _err(f"error: bad --pattern: {exc}")
            return 2
        if profile.is_empty:
            _err("note: no structural requirements found in the query; nothing to rank (try --mode bm25)")
        records, reason = ensure_ast_records(units, args.index_dir)
        if reason:
            _err(f"AST features extracted ({reason}): {len(records)} units")
        fragments = None
        if profile.relations:
            fragments, reason = ensure_fragment_records(units, args.index_dir)
            if reason:
                _err(f"fragments extracted ({reason}): {len(fragments)} units")
        results = structural_search(profile, units_by_id, records, args.k, args.query_id, failed_by_path, fragments)
        extra["profile"] = profile.to_dict()
        _err(f"structural profile ({profile.source}): {profile.describe()}")
    elif args.mode == "like":
        snippet = args.query
        if snippet.startswith("@"):
            try:
                snippet = Path(snippet[1:]).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                _err(f"error: cannot read snippet file {snippet[1:]}: {exc}")
                return 2
        try:
            wanted = snippet_terms(snippet)
        except ValueError as exc:
            _err(f"error: {exc}")
            return 2
        fragments, reason = ensure_fragment_records(units, args.index_dir)
        if reason:
            _err(f"fragments extracted ({reason}): {len(fragments)} units")
        results = like_search(FragmentIndex(fragments), units_by_id, wanted, args.k, args.query_id, failed_by_path)
    elif args.mode == "dense":
        dense_index, embedder, settings = _dense(args, cfg, units)
        results = dense_search(
            dense_index, embedder, settings, units_by_id, args.query, args.k, args.query_id, failed_by_path
        )
        extra["embedding_model"] = dense_index.model
    else:
        if not tokenize_query(args.query):
            _err("note: the query has no searchable terms after removing stopwords")
        results = bm25_search(bm25_index, units_by_id, args.query, args.k, args.query_id, failed_by_path)

    if args.json:
        payload = {
            "query": args.query,
            "mode": args.mode,
            "k": args.k,
            "units_indexed": len(units),
            **extra,
            "results": [result_to_dict(r, units_by_id[r.unit_id], args.lines) for r in results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_results(args.query, results, units_by_id, len(units), args.lines, args.mode))
    return 0
