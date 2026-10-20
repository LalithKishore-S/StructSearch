"""Ingestion command line: python -m structsearch.ingestion [corpus] [--out FILE]"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from structsearch.config import load_config
from structsearch.ingestion.corpus import ingest_corpus, save_failed, save_units


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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    result = ingest_corpus(args.corpus, include_failed=not args.skip_failed)
    save_units(result.units, args.out)
    failed_path = Path(args.out).with_name("failed_files.json")
    save_failed(result.failed_files, failed_path)

    failed_units = sum(1 for u in result.units if u.parse_status != "ok")
    print(f"files scanned : {result.files_scanned}")
    print(f"units         : {len(result.units)} ({failed_units} file-level units from failed files)")
    print(f"failed files  : {len(result.failed_files)}")
    for item in result.failed_files:
        where = f" (line {item.line})" if item.line else ""
        print(f"  - {item.rel_path}{where}: {item.error}")
    if args.list:
        for unit in result.units:
            flag = "  [parse failed]" if unit.parse_status != "ok" else ""
            print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]{flag}")
    print(f"written to    : {args.out}")
    print(f"failure report: {failed_path}")
    return 0
