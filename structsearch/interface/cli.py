"""StructSearch command line.

  python -m structsearch index [CORPUS] [--dense]       build/refresh the index(es)
  python -m structsearch search "read file" -k 5        BM25 search (builds the index if needed)
  python -m structsearch search "check credentials" --mode dense   semantic search (needs Ollama)

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
from structsearch.retrieval.baseline import bm25_search
from structsearch.retrieval.dense import dense_search

MODES = ("bm25", "dense")  # text_ast and hybrid are added in later steps


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
    return parser


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


def _run(args, cfg) -> int:
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
    if args.mode == "dense":
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
