"""Cache of AST features next to the other index files (ast_features.jsonl).

First line is a header with the extraction version and a fingerprint of the units; the
file is recomputed when either changes, so stale features are never used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from structsearch.ingestion.corpus import fingerprint_units
from structsearch.parsing.features import EXTRACTION_VERSION, extract_all
from structsearch.schemas import AstRecord, CodeUnit

AST_FILE = "ast_features.jsonl"


def save_ast_records(records: Sequence[AstRecord], path: Union[str, Path], fingerprint: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"_meta": {"extraction_version": EXTRACTION_VERSION, "fingerprint": fingerprint}}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(header) + "\n")
        for record in records:
            handle.write(json.dumps(record.to_dict()) + "\n")


def load_ast_records(path: Union[str, Path]) -> Optional[Tuple[str, List[AstRecord]]]:
    """Return (fingerprint, records), or None if the file is missing, unreadable or outdated."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.loads(handle.readline())["_meta"]
            if meta.get("extraction_version") != EXTRACTION_VERSION:
                return None
            return meta["fingerprint"], [AstRecord.from_dict(json.loads(l)) for l in handle if l.strip()]
    except (OSError, ValueError, KeyError):
        return None


def ensure_ast_records(
    units: Sequence[CodeUnit], index_dir: Union[str, Path]
) -> Tuple[List[AstRecord], Optional[str]]:
    """Load cached features if they match the units, else extract and cache them.

    Returns (records aligned with units, reason); reason is None when the cache was reused.
    """
    path = Path(index_dir) / AST_FILE
    fingerprint = fingerprint_units(units)
    cached = load_ast_records(path)
    if cached is not None and cached[0] == fingerprint:
        by_id = {r.unit_id: r for r in cached[1]}
        if all(u.unit_id in by_id for u in units):
            return [by_id[u.unit_id] for u in units], None
    reason = "no AST features yet" if cached is None else "units changed"
    records = extract_all(units)
    save_ast_records(records, path, fingerprint)
    return records, reason


# --------------------------------------------------------------------------- fragments

from structsearch.parsing.fragments import (  # noqa: E402  (kept next to the code that uses it)
    FRAGMENT_VERSION,
    FragmentRecord,
    extract_all_fragments,
)

FRAGMENT_FILE = "fragments.jsonl"


def save_fragment_records(records: Sequence[FragmentRecord], path: Union[str, Path], fingerprint: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"_meta": {"extraction_version": FRAGMENT_VERSION, "fingerprint": fingerprint}}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(header) + "\n")
        for record in records:
            handle.write(json.dumps(record.to_dict()) + "\n")


def load_fragment_records(path: Union[str, Path]) -> Optional[Tuple[str, List[FragmentRecord]]]:
    """Return (fingerprint, records), or None if the file is missing, unreadable or outdated."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.loads(handle.readline())["_meta"]
            if meta.get("extraction_version") != FRAGMENT_VERSION:
                return None
            return meta["fingerprint"], [FragmentRecord.from_dict(json.loads(l)) for l in handle if l.strip()]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ensure_fragment_records(
    units: Sequence[CodeUnit], index_dir: Union[str, Path]
) -> Tuple[List[FragmentRecord], Optional[str]]:
    """Same contract as ensure_ast_records, for fragment terms (fragments.jsonl)."""
    path = Path(index_dir) / FRAGMENT_FILE
    fingerprint = fingerprint_units(units)
    cached = load_fragment_records(path)
    if cached is not None and cached[0] == fingerprint:
        by_id = {r.unit_id: r for r in cached[1]}
        if all(u.unit_id in by_id for u in units):
            return [by_id[u.unit_id] for u in units], None
    reason = "no fragment index yet" if cached is None else "units changed"
    records = extract_all_fragments(units)
    save_fragment_records(records, path, fingerprint)
    return records, reason
