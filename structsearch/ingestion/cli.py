"""Ingestion command line: python -m structsearch.ingestion [corpus] [--out FILE]"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from structsearch.config import load_config
from structsearch.ingestion.corpus import ingest_corpus, save_failed, save_units
from structsearch.parsing.tolerant import TolerantUnavailable
from structsearch.schemas import status_flag


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Split a Python corpus into function units.")
    parser.add_argument("corpus", nargs="?", default=cfg["corpus_path"])
    parser.add_argument("--out", default=str(Path(cfg["index_dir"]) / "units.jsonl"))
    parser.add_argument("--list", action="store_true", help="print every unit id")
    parser.add_argument(
        "--skip-failed",
        action="store_true",
        help="do not keep unparseable files as file-level units",
    )
    parser.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    try:
        result = ingest_corpus(args.corpus, include_failed=not args.skip_failed, tolerant=args.tolerant)
    except TolerantUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    save_units(result.units, args.out)
    failed_path = Path(args.out).with_name("failed_files.json")
    save_failed(result.failed_files, failed_path)

    failed_units = sum(1 for u in result.units if u.parse_status != "ok")
    partial = sum(1 for u in result.units if u.parse_status == "partial")
    print(f"files scanned : {result.files_scanned}")
    print(f"units         : {len(result.units)} ({failed_units} not fully parsed, {partial} of them partial)")
    print(f"failed files  : {len(result.failed_files)}")
    for item in result.failed_files:
        where = f" (line {item.line})" if item.line else ""
        print(f"  - {item.rel_path}{where}: {item.error}")
        if item.recovered_units or item.error_lines:
            print(f"      recovered {item.recovered_units} function(s); syntax errors at lines {item.error_lines}")
    if args.list:
        for unit in result.units:
            print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]{status_flag(unit)}")
    print(f"written to    : {args.out}")
    print(f"failure report: {failed_path}")
    return 0
