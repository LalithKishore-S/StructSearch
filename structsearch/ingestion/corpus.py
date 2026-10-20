"""Walk a corpus directory and ingest every Python file."""
from __future__ import annotations

import json
import logging
import os
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple, Union

from structsearch.ingestion.segmenter import split_source
from structsearch.schemas import CodeUnit

log = logging.getLogger(__name__)

SKIP_DIRS = {
    "__pycache__", "node_modules", "site-packages", "build", "dist", "venv", "env",
}


@dataclass
class IngestResult:
    units: List[CodeUnit] = field(default_factory=list)
    failed_files: List[Tuple[str, str]] = field(default_factory=list)  # (rel_path, error)
    files_scanned: int = 0


def _iter_py_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # Deterministic order; skip hidden dirs (.git, .venv, .structsearch_index, ...)
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def ingest_corpus(root: Union[str, Path]) -> IngestResult:
    """Ingest all .py files under root. Unparseable files are recorded, not fatal."""
    root = Path(root).resolve()
    base = root.parent if root.is_file() else root
    result = IngestResult()
    for path in _iter_py_files(root):
        rel = path.relative_to(base).as_posix()
        result.files_scanned += 1
        try:
            with tokenize.open(path) as handle:  # honors PEP 263 encoding cookies
                source = handle.read()
            result.units.extend(split_source(source, rel))
        except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError, OSError) as exc:
            result.failed_files.append((rel, f"{type(exc).__name__}: {exc}"))
            log.warning("skipping %s: %s", rel, exc)
    result.units.sort(key=lambda u: u.unit_id)
    return result


def save_units(units: Iterable[CodeUnit], path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for unit in units:
            handle.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")


def load_units(path: Union[str, Path]) -> List[CodeUnit]:
    with open(path, "r", encoding="utf-8") as handle:
        return [CodeUnit.from_dict(json.loads(line)) for line in handle if line.strip()]
