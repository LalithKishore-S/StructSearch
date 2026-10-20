"""Glue: corpus -> units -> text records -> BM25 index, saved under one index folder.

Index folder contents
  units.jsonl        function-level CodeUnits (plus file-level units for failed files)
  failed_files.json  files that did not parse (error message and line)
  bm25_index.json    tokenized fields and BM25 parameters
  meta.json          which corpus the index was built from (path, file signature)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from structsearch.config import load_config
from structsearch.indexing.bm25 import BM25Index
from structsearch.indexing.records import build_text_records
from structsearch.ingestion.corpus import (
    IngestResult,
    corpus_signature,
    fingerprint_units,
    ingest_corpus,
    load_units,
    save_failed,
    save_units,
)
from structsearch.schemas import CodeUnit

log = logging.getLogger(__name__)

UNITS_FILE = "units.jsonl"
FAILED_FILE = "failed_files.json"
BM25_FILE = "bm25_index.json"
META_FILE = "meta.json"
META_VERSION = 1


def build_index(units: List[CodeUnit], cfg: Optional[Dict[str, Any]] = None) -> BM25Index:
    cfg = cfg or load_config()
    params = cfg.get("bm25", {})
    return BM25Index.build(
        build_text_records(units),
        field_weights=params.get("field_weights"),
        k1=params.get("k1", 1.5),
        b=params.get("b", 0.75),
        fingerprint=fingerprint_units(units),
    )


def build_all(
    corpus: Union[str, Path],
    index_dir: Union[str, Path],
    cfg: Optional[Dict[str, Any]] = None,
    include_failed: bool = True,
) -> Tuple[IngestResult, BM25Index]:
    """Ingest a corpus, build the BM25 index and save everything to index_dir."""
    index_dir = Path(index_dir)
    signature = corpus_signature(corpus)  # taken before reading, so edits during a build are caught later
    result = ingest_corpus(corpus, include_failed=include_failed)
    save_units(result.units, index_dir / UNITS_FILE)
    save_failed(result.failed_files, index_dir / FAILED_FILE)
    index = build_index(result.units, cfg)
    index.save(index_dir / BM25_FILE)
    meta = {
        "version": META_VERSION,
        "corpus": str(Path(corpus).resolve()),
        "signature": signature,
        "include_failed": include_failed,
    }
    (index_dir / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result, index


def load_all(
    index_dir: Union[str, Path], cfg: Optional[Dict[str, Any]] = None
) -> Tuple[List[CodeUnit], BM25Index]:
    """Load units and the BM25 index; rebuild the index if it no longer matches the units."""
    index_dir = Path(index_dir)
    units = load_units(index_dir / UNITS_FILE)
    bm25_path = index_dir / BM25_FILE
    if bm25_path.exists():
        index = BM25Index.load(bm25_path)
        if index.fingerprint == fingerprint_units(units):
            return units, index
        log.warning("BM25 index is stale; rebuilding from units.jsonl")
    index = build_index(units, cfg)
    index.save(bm25_path)
    return units, index


def _read_meta(index_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        meta = json.loads((index_dir / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if meta.get("version") == META_VERSION else None


def ensure_index(
    corpus: Union[str, Path],
    index_dir: Union[str, Path],
    cfg: Optional[Dict[str, Any]] = None,
    include_failed: bool = True,
    rebuild: bool = False,
) -> Tuple[List[CodeUnit], BM25Index, Optional[str]]:
    """Load the saved index, or (re)build it when missing or out of date.

    Returns (units, index, reason). reason says why a build happened, or is None
    when the saved index was reused.
    """
    index_dir = Path(index_dir)
    meta = _read_meta(index_dir)
    reason: Optional[str] = None
    if rebuild:
        reason = "rebuild requested"
    elif meta is None or not (index_dir / UNITS_FILE).exists() or not (index_dir / BM25_FILE).exists():
        reason = "no index yet"
    elif meta.get("corpus") != str(Path(corpus).resolve()):
        reason = "corpus path changed"
    elif meta.get("include_failed") != include_failed:
        reason = "failed-file setting changed"
    elif meta.get("signature") != corpus_signature(corpus):
        reason = "corpus files changed"
    if reason:
        result, index = build_all(corpus, index_dir, cfg, include_failed)
        return result.units, index, reason
    units, index = load_all(index_dir, cfg)
    return units, index, None
