"""Build and query the BM25 index.

  python -m structsearch.indexing [corpus] [--index-dir DIR] [--query "read file"] [-k 5]
  python -m structsearch.indexing --load --query "recursive tree traversal"

The full search interface (with excerpts and modes) arrives in Step 3.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from structsearch.config import load_config
from structsearch.indexing.builder import build_all, load_all
from structsearch.parsing.tolerant import TolerantUnavailable
from structsearch.schemas import status_flag


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Build/query the BM25 index.")
    parser.add_argument("corpus", nargs="?", default=cfg["corpus_path"])
    parser.add_argument("--index-dir", default=cfg["index_dir"])
    parser.add_argument("--load", action="store_true", help="use the saved index, do not re-ingest")
    parser.add_argument("--skip-failed", action="store_true", help="exclude unparseable files")
    parser.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    parser.add_argument("--query", help="run a query after building/loading")
    parser.add_argument("-k", type=int, default=cfg["top_k"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="%(message)s")  # failures are summarized below
    index_dir = Path(args.index_dir)
    if args.load:
        units, index = load_all(index_dir, cfg)
        print(f"loaded {len(units)} units from {index_dir}")
    else:
        try:
            result, index = build_all(args.corpus, index_dir, cfg, include_failed=not args.skip_failed, tolerant=args.tolerant)
        except TolerantUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        units = result.units
        print(f"files scanned : {result.files_scanned}")
        print(f"units indexed : {len(units)}")
        print(f"failed files  : {len(result.failed_files)}")
        print(f"index saved to: {index_dir}")

    if args.query:
        by_id = {u.unit_id: u for u in units}
        hits = index.search(args.query, args.k)
        print(f'\nTop {len(hits)} for "{args.query}":')
        for rank, hit in enumerate(hits, 1):
            unit = by_id[hit.unit_id]
            flag = status_flag(unit)
            fields = index.explain(args.query, hit.unit_id)
            matched = "; ".join(f"{f}: {', '.join(t)}" for f, t in fields.items())
            print(f"{rank:2d}. {hit.score:7.3f}  {hit.unit_id}  [{unit.start_line}-{unit.end_line}]{flag}")
            print(f"            matched -> {matched}")
    return 0
