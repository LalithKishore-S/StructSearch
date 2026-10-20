"""StructSearch command line.

  python -m structsearch index [CORPUS]                 build/refresh the index
  python -m structsearch search "read file" -k 5        search (builds the index if needed)

Status messages go to stderr so that --json output on stdout stays clean.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from structsearch.config import load_config
from structsearch.indexing.builder import FAILED_FILE, ensure_index
from structsearch.indexing.tokenizer import tokenize_query
from structsearch.ingestion.corpus import load_failed
from structsearch.interface.format import format_results, result_to_dict
from structsearch.retrieval.baseline import bm25_search

MODES = ("bm25",)  # dense, text_ast and hybrid are added in later steps


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _build_parser(cfg) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="structsearch", description="Structure-aware code search.")
    sub = parser.add_subparsers(dest="command", required=True)

    index_p = sub.add_parser("index", help="build or refresh the index")
    index_p.add_argument("corpus", nargs="?", default=cfg["corpus_path"], help="folder (or file) to index")
    index_p.add_argument("--index-dir", default=cfg["index_dir"])
    index_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    index_p.add_argument("--rebuild", action="store_true", help="force a rebuild")

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


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    args = _build_parser(cfg).parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="%(message)s")

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
        print(f"index folder  : {args.index_dir}")
        return 0

    # search
    if args.k < 1:
        _err("error: -k must be at least 1")
        return 2
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, index = loaded
    if not tokenize_query(args.query):
        _err("note: the query has no searchable terms after removing stopwords")

    units_by_id = {u.unit_id: u for u in units}
    failed_by_path = {f.rel_path: f for f in load_failed(Path(args.index_dir) / FAILED_FILE)}
    results = bm25_search(index, units_by_id, args.query, args.k, args.query_id, failed_by_path)

    if args.json:
        payload = {
            "query": args.query,
            "mode": args.mode,
            "k": args.k,
            "units_indexed": len(units),
            "results": [result_to_dict(r, units_by_id[r.unit_id], args.lines) for r in results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_results(args.query, results, units_by_id, len(units), args.lines, args.mode))
    return 0
