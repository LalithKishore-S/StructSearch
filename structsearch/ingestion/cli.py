"""Ingestion command line: python -m structsearch.ingestion [corpus] [--out FILE]"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from structsearch.config import load_config
from structsearch.ingestion.corpus import ingest_corpus, save_units


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Split a Python corpus into function units.")
    parser.add_argument("corpus", nargs="?", default=cfg["corpus_path"])
    parser.add_argument("--out", default=str(Path(cfg["index_dir"]) / "units.jsonl"))
    parser.add_argument("--list", action="store_true", help="print every unit id")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    result = ingest_corpus(args.corpus)
    save_units(result.units, args.out)

    print(f"files scanned : {result.files_scanned}")
    print(f"units         : {len(result.units)}")
    print(f"failed files  : {len(result.failed_files)}")
    for rel, err in result.failed_files:
        print(f"  - {rel}: {err}")
    if args.list:
        for unit in result.units:
            print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]")
    print(f"written to    : {args.out}")
    return 0
