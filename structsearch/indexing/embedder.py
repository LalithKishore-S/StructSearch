"""Embedding backends for the dense (semantic) baseline.

OllamaEmbedder   real semantic embeddings from a local Ollama server (default backend).
HashingEmbedder  deterministic bag-of-subwords vectors. Lexical, NOT semantic: it exists so
                 the dense pipeline can be tested and demoed without Ollama.

Only the standard library is used for HTTP, so there is no extra dependency.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from structsearch.indexing.tokenizer import tokenize_text


class EmbeddingError(RuntimeError):
    """Embedding backend unavailable or returned something unusable."""


@dataclass(frozen=True)
class DenseSettings:
    backend: str = "ollama"  # "ollama" or "hashing"
    model: str = "nomic-embed-text"
    host: str = "http://localhost:11434"
    doc_prefix: str = "search_document: "  # nomic-embed-text expects these task prefixes
    query_prefix: str = "search_query: "
    max_chars: int = 4000  # source text is cut to this length before embedding
    batch_size: int = 16
    timeout_seconds: float = 120.0

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None, **overrides: Any) -> "DenseSettings":
        base = cls()
        section = (cfg or {}).get("dense", {}) or {}
        known = {k: v for k, v in section.items() if k in cls.__dataclass_fields__}
        settings = replace(base, **known)
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(settings, **clean)


class Embedder:
    """Interface: model is a stable name used in cache keys; embed returns an (n, dim) array."""

    model: str = ""

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError


class _EndpointMissing(Exception):
    pass


class OllamaEmbedder(Embedder):
    def __init__(self, model: str, host: str = "http://localhost:11434", timeout: float = 120.0):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 404:
                if "model" in body.lower() and ("not found" in body.lower() or "pull" in body.lower()):
                    raise EmbeddingError(
                        f"Ollama does not have the model '{self.model}'. Run: ollama pull {self.model}"
                    ) from exc
                raise _EndpointMissing(path) from exc
            raise EmbeddingError(f"Ollama returned HTTP {exc.code} for {path}: {body[:200]}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingError(
                f"Cannot reach Ollama at {self.host} ({exc.reason}). "
                f"Start it (ollama serve) and run: ollama pull {self.model}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise EmbeddingError(f"Ollama request to {self.host} failed: {exc}") from exc
        except ValueError as exc:
            raise EmbeddingError(f"Ollama sent a response that is not valid JSON: {exc}") from exc

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        try:
            vectors = self._post("/api/embed", {"model": self.model, "input": texts})["embeddings"]
        except _EndpointMissing:  # older Ollama: one text per request
            vectors = [
                self._post("/api/embeddings", {"model": self.model, "prompt": t})["embedding"]
                for t in texts
            ]
        except KeyError as exc:
            raise EmbeddingError("Ollama response has no 'embeddings' field") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(f"asked for {len(texts)} embeddings, Ollama returned {len(vectors)}")
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] == 0:
            raise EmbeddingError("Ollama returned empty or malformed embeddings")
        return array


class HashingEmbedder(Embedder):
    """Signed feature hashing of subword tokens. Deterministic across runs and machines."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.model = f"hashing-{dim}"

    def _tokens(self, text: str) -> List[str]:
        return tokenize_text(text)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in self._tokens(text):
                digest = hashlib.md5(token.encode("utf-8")).digest()
                slot = int.from_bytes(digest[:4], "big") % self.dim
                out[row, slot] += 1.0 if digest[4] & 1 else -1.0
        return out


def make_embedder(settings: DenseSettings) -> Embedder:
    if settings.backend == "ollama":
        return OllamaEmbedder(settings.model, settings.host, settings.timeout_seconds)
    if settings.backend == "hashing":
        return HashingEmbedder()
    raise ValueError(f"unknown dense backend: {settings.backend}")
