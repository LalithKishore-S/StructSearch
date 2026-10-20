"""Walk a corpus directory and ingest every Python file."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple, Union

from structsearch.ingestion.segmenter import make_file_unit, split_source
from structsearch.schemas import CodeUnit

log = logging.getLogger(__name__)

SKIP_DIRS = {
    "__pycache__", "node_modules", "site-packages", "build", "dist", "venv", "env",
}


@dataclass
class FailedFile:
    rel_path: str
    error: str
    line: Optional[int] = None  # line of the syntax error, when known


@dataclass
class IngestResult:
    units: List[CodeUnit] = field(default_factory=list)
    failed_files: List[FailedFile] = field(default_factory=list)
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


def _read_source(path: Path) -> Tuple[str, Optional[FailedFile]]:
    """Read a file honoring PEP 263 cookies. On bad encoding return lossy text + error."""
    try:
        with tokenize.open(path) as handle:
            return handle.read(), None
    except (SyntaxError, UnicodeDecodeError) as exc:
        text = path.read_bytes().decode("utf-8", errors="replace")
        return text, FailedFile("", f"{type(exc).__name__}: {exc}", getattr(exc, "lineno", None))


def ingest_corpus(root: Union[str, Path], include_failed: bool = True) -> IngestResult:
    """Ingest all .py files under root.

    Unparseable files are never fatal. They are listed in failed_files and, unless
    include_failed is False, kept as one file-level unit with parse_status='failed'.
    """
    root = Path(root).resolve()
    base = root.parent if root.is_file() else root
    result = IngestResult()
    for path in _iter_py_files(root):
        rel = path.relative_to(base).as_posix()
        result.files_scanned += 1
        try:
            source, failure = _read_source(path)
        except OSError as exc:  # cannot even read the bytes: nothing to index
            result.failed_files.append(FailedFile(rel, f"OSError: {exc}"))
            log.warning("cannot read %s: %s", rel, exc)
            continue

        if failure is None:
            try:
                result.units.extend(split_source(source, rel))
                continue
            except (SyntaxError, ValueError, RecursionError) as exc:
                failure = FailedFile("", f"{type(exc).__name__}: {exc}", getattr(exc, "lineno", None))

        failure.rel_path = rel
        result.failed_files.append(failure)
        log.warning("parse failed for %s: %s", rel, failure.error)
        if include_failed:
            result.units.append(make_file_unit(source, rel))
    result.units.sort(key=lambda u: u.unit_id)
    return result


def fingerprint_units(units: Iterable[CodeUnit]) -> str:
    """Stable hash of unit ids and source text; used to detect stale indexes."""
    digest = hashlib.sha256()
    for unit in sorted(units, key=lambda u: u.unit_id):
        digest.update(unit.unit_id.encode("utf-8", "replace"))
        digest.update(b"\0")
        digest.update(unit.source_text.encode("utf-8", "replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def save_units(units: Iterable[CodeUnit], path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for unit in units:
            handle.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")


def load_units(path: Union[str, Path]) -> List[CodeUnit]:
    with open(path, "r", encoding="utf-8") as handle:
        return [CodeUnit.from_dict(json.loads(line)) for line in handle if line.strip()]


def save_failed(failed: Iterable[FailedFile], path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([asdict(f) for f in failed], handle, indent=2, ensure_ascii=False)


def load_failed(path: Union[str, Path]) -> List[FailedFile]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [FailedFile(**item) for item in json.load(handle)]
