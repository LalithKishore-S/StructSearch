"""Cache of the code graph next to the other index files (graph.json).

The file carries the graph version and a fingerprint of the units; it is rebuilt when either
changes, so a stale graph is never used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

from structsearch.graph.builder import build_graph
from structsearch.graph.markers import describe_markers
from structsearch.graph.model import GRAPH_VERSION, CodeGraph
from structsearch.ingestion.corpus import fingerprint_units
from structsearch.schemas import CodeUnit

GRAPH_FILE = "graph.json"


def markers_signature() -> str:
    """Short hash of the default marker table, so a graph built with another table is not reused."""
    return hashlib.sha256(json.dumps(describe_markers(), sort_keys=True).encode("utf-8")).hexdigest()[:12]


def save_graph(graph: CodeGraph, path: Union[str, Path], fingerprint: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_meta": {"graph_version": GRAPH_VERSION, "fingerprint": fingerprint}, **graph.to_dict()}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load_graph(path: Union[str, Path]) -> Optional[Tuple[str, CodeGraph]]:
    """Return (fingerprint, graph), or None if the file is missing, unreadable or outdated."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        meta = data["_meta"]
        if meta.get("graph_version") != GRAPH_VERSION:
            return None
        return meta["fingerprint"], CodeGraph.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ensure_graph(units: Sequence[CodeUnit], index_dir: Union[str, Path]) -> Tuple[CodeGraph, Optional[str]]:
    """Load the cached graph if it matches the units, else build and cache it.

    Returns (graph, reason); reason is None when the cache was reused.
    """
    path = Path(index_dir) / GRAPH_FILE
    fingerprint = f"{fingerprint_units(units)}:{markers_signature()}"
    cached = load_graph(path)
    if cached is not None and cached[0] == fingerprint:
        return cached[1], None
    reason = "no graph yet" if cached is None else "units or markers changed"
    graph = build_graph(units)
    save_graph(graph, path, fingerprint)
    return graph, reason
