"""Config loading and validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "default.yaml"
REQUIRED_WEIGHTS = ("text", "structural", "graph")


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    return cfg


def validate_config(cfg: Dict[str, Any]) -> None:
    weights = cfg.get("weights", {})
    for key in REQUIRED_WEIGHTS:
        if key not in weights:
            raise ValueError(f"missing weight: {key}")
        if weights[key] < 0:
            raise ValueError(f"negative weight: {key}")
    if sum(weights.values()) <= 0:
        raise ValueError("weights must not all be zero")
    if int(cfg.get("top_k", 0)) < 1:
        raise ValueError("top_k must be >= 1")
    bm25 = cfg.get("bm25")
    if bm25 is not None:
        if bm25.get("k1", 1.5) <= 0:
            raise ValueError("bm25.k1 must be > 0")
        if not 0 <= bm25.get("b", 0.75) <= 1:
            raise ValueError("bm25.b must be between 0 and 1")
        for name, weight in bm25.get("field_weights", {}).items():
            if weight < 0:
                raise ValueError(f"negative bm25 field weight: {name}")
    dense = cfg.get("dense")
    if dense is not None:
        if dense.get("backend", "ollama") not in ("ollama", "hashing"):
            raise ValueError("dense.backend must be 'ollama' or 'hashing'")
        if int(dense.get("batch_size", 16)) < 1:
            raise ValueError("dense.batch_size must be >= 1")
        if int(dense.get("max_chars", 4000)) < 100:
            raise ValueError("dense.max_chars must be >= 100")
        if float(dense.get("timeout_seconds", 120)) <= 0:
            raise ValueError("dense.timeout_seconds must be > 0")
        if not str(dense.get("model", "x")).strip():
            raise ValueError("dense.model must not be empty")
