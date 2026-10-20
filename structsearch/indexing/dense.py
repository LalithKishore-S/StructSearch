"""Dense (semantic) index: one L2-normalized vector per unit, exact cosine search.

Stored as plain files (no vector database): dense_vectors.npy (float32 matrix) and
dense_meta.json (unit ids, per-unit text hashes, model name). Search is one matrix-vector
product, so results are exact and reproducible. Everything sits behind DenseIndex, so
FAISS or Chroma could replace the numpy matrix later without touching callers.

Re-embedding is the slow part, so vectors are cached by a hash of (model, embedded text):
when the corpus changes, only new or edited units are sent to the embedder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from structsearch.indexing.embedder import DenseSettings, Embedder, EmbeddingError
from structsearch.schemas import CodeUnit

VECTORS_FILE = "dense_vectors.npy"
META_FILE = "dense_meta.json"
DENSE_VERSION = 1

Progress = Callable[[int, int], None]


def embedding_text(unit: CodeUnit, settings: DenseSettings) -> str:
    """Text sent to the embedder: qualified name, file, then source (cut to max_chars)."""
    qual = unit.unit_id.split("::", 1)[-1]
    name = unit.name if qual == "<module>" else qual
    body = unit.source_text[: settings.max_chars]
    return f"{settings.doc_prefix}{name} ({unit.file_path})\n{body}"


def text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode("utf-8", "replace")).hexdigest()


def normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows; all-zero rows stay zero.

    Idempotent: rows that already have unit length are returned untouched, so saving,
    loading and reusing vectors never changes them (re-normalizing would shift the last
    float32 digit and break exact score reproducibility).
    """
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    needs_scaling = (norms > 0) & (np.abs(norms - 1.0) > 1e-5)
    return np.where(needs_scaling, vectors / np.where(norms == 0, 1.0, norms), vectors)


def embed_query(embedder: Embedder, settings: DenseSettings, query: str) -> np.ndarray:
    return normalize(embedder.embed([settings.query_prefix + query]))[0]


class DenseIndex:
    def __init__(
        self,
        unit_ids: Sequence[str],
        vectors: np.ndarray,
        text_hashes: Sequence[str],
        model: str,
    ):
        self.unit_ids: List[str] = list(unit_ids)
        self.vectors = normalize(vectors) if len(unit_ids) else np.zeros((0, 0), dtype=np.float32)
        self.text_hashes: List[str] = list(text_hashes)
        self.model = model

    @property
    def dim(self) -> int:
        return int(self.vectors.shape[1]) if self.vectors.ndim == 2 else 0

    def score_all(self, query_vector: np.ndarray) -> np.ndarray:
        """Cosine similarity with every unit, aligned with self.unit_ids (used by fusion later)."""
        if not self.unit_ids:
            return np.zeros(0, dtype=np.float32)
        query = normalize(np.asarray(query_vector, dtype=np.float32))
        if query.shape[-1] != self.dim:
            raise EmbeddingError(
                f"query vector has {query.shape[-1]} dimensions but the index has {self.dim}; "
                "rebuild the dense index (--rebuild)"
            )
        # Some BLAS builds (seen on macOS) raise spurious floating-point warnings from this
        # product even though the numbers are fine, so warnings are silenced and the result
        # is checked explicitly instead.
        with np.errstate(all="ignore"):
            scores = self.vectors @ query
        if not np.isfinite(scores).all():
            raise EmbeddingError(
                "similarity scores contain NaN or infinity; rebuild the dense index (--rebuild)"
            )
        return scores

    def search(self, query_vector: np.ndarray, k: int = 10) -> List[Tuple[str, float]]:
        scores = self.score_all(query_vector)
        order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.unit_ids[i]))
        return [(self.unit_ids[i], float(scores[i])) for i in order[:k]]

    # ---- persistence ----
    def save(self, directory: Union[str, Path]) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / VECTORS_FILE, self.vectors.astype(np.float32), allow_pickle=False)
        meta = {
            "version": DENSE_VERSION,
            "model": self.model,
            "dim": self.dim,
            "unit_ids": self.unit_ids,
            "text_hashes": self.text_hashes,
        }
        (directory / META_FILE).write_text(json.dumps(meta), encoding="utf-8")

    @classmethod
    def load(cls, directory: Union[str, Path]) -> Optional["DenseIndex"]:
        """Return the saved index, or None if it is missing, unreadable or an old version."""
        directory = Path(directory)
        try:
            meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
            if meta.get("version") != DENSE_VERSION:
                return None
            vectors = np.load(directory / VECTORS_FILE, allow_pickle=False)
            if vectors.shape[0] != len(meta["unit_ids"]):
                return None
            return cls(meta["unit_ids"], vectors, meta["text_hashes"], meta["model"])
        except (OSError, ValueError, KeyError):
            return None


def _texts_and_hashes(
    units: Sequence[CodeUnit], embedder: Embedder, settings: DenseSettings
) -> Tuple[List[str], List[str]]:
    texts = [embedding_text(u, settings) for u in units]
    return texts, [text_hash(embedder.model, t) for t in texts]


def build_dense_index(
    units: Sequence[CodeUnit],
    embedder: Embedder,
    settings: DenseSettings,
    previous: Optional[DenseIndex] = None,
    progress: Optional[Progress] = None,
) -> DenseIndex:
    """Embed the units. Vectors of unchanged units are reused from `previous`."""
    texts, hashes = _texts_and_hashes(units, embedder, settings)
    cache: Dict[str, np.ndarray] = {}
    if previous is not None and previous.model == embedder.model:
        cache.update(zip(previous.text_hashes, previous.vectors))

    todo: Dict[str, str] = {}  # hash -> text, each distinct text embedded once
    for text, digest in zip(texts, hashes):
        if digest not in cache and digest not in todo:
            todo[digest] = text
    items = list(todo.items())
    for start in range(0, len(items), settings.batch_size):
        chunk = items[start : start + settings.batch_size]
        vectors = embedder.embed([text for _, text in chunk])
        if len(vectors) != len(chunk):
            raise EmbeddingError("embedder returned the wrong number of vectors")
        if not np.isfinite(vectors).all():
            raise EmbeddingError("embedder returned NaN or infinite values")
        for (digest, _), vector in zip(chunk, vectors):
            cache[digest] = normalize(vector)
        if progress:
            progress(min(start + settings.batch_size, len(items)), len(items))

    if not units:
        return DenseIndex([], np.zeros((0, 0), dtype=np.float32), [], embedder.model)
    matrix = np.vstack([cache[h] for h in hashes])
    return DenseIndex([u.unit_id for u in units], matrix, hashes, embedder.model)


def ensure_dense_index(
    units: Sequence[CodeUnit],
    index_dir: Union[str, Path],
    embedder: Embedder,
    settings: DenseSettings,
    rebuild: bool = False,
    progress: Optional[Progress] = None,
) -> Tuple[DenseIndex, Optional[str]]:
    """Load the saved dense index if it matches the units, else (re)build and save it.

    Returns (index, reason); reason is None when the saved index was reused.
    """
    previous = DenseIndex.load(index_dir)
    _, hashes = _texts_and_hashes(units, embedder, settings)
    ids = [u.unit_id for u in units]
    if rebuild:
        reason = "rebuild requested"
    elif previous is None:
        reason = "no dense index yet"
    elif previous.unit_ids != ids or previous.text_hashes != hashes:
        known = set(previous.text_hashes)
        fresh = sum(1 for h in set(hashes) if h not in known)
        reason = f"units changed ({fresh} to embed)"
    else:
        return previous, None
    index = build_dense_index(units, embedder, settings, None if rebuild else previous, progress)
    index.save(index_dir)
    return index, reason
