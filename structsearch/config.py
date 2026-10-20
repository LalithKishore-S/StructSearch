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
