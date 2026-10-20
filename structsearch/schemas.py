"""Shared data contracts between Member 1 and Member 2.

Do not change field names without agreeing with the other member.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

PARSE_OK = "ok"
PARSE_FAILED = "failed"


class _Record:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class CodeUnit(_Record):
    """One function or method. unit_id format: '<relative/path.py>::<qualname>'."""

    unit_id: str
    file_path: str
    start_line: int
    end_line: int
    name: str
    source_text: str
    language: str = "python"
    parse_status: str = PARSE_OK


@dataclass
class TextRecord(_Record):
    unit_id: str
    name: str
    identifiers: List[str] = field(default_factory=list)
    docstring_comments: str = ""
    code_tokens: List[str] = field(default_factory=list)


@dataclass
class AstRecord(_Record):
    unit_id: str
    features: Dict[str, float] = field(default_factory=dict)
    extraction_version: str = "0"
    parse_status: str = PARSE_OK


@dataclass
class RankedResult(_Record):
    """graph_score is None until the graph module is integrated.

    dense_score (semantic cosine similarity) is None unless the dense variant ran. It was
    added at the end of the record so existing positional uses keep working.
    """

    query_id: str
    unit_id: str
    text_score: float = 0.0
    structural_score: float = 0.0
    graph_score: Optional[float] = None
    final_score: float = 0.0
    evidence: List[str] = field(default_factory=list)
    dense_score: Optional[float] = None


@dataclass
class EvaluationLabel(_Record):
    """Owned by Member 2; included so both sides agree on the format."""

    query_id: str
    unit_id: str
    relevance: int  # 0 = not relevant, 1 = relevant (graded 2+ allowed later)
    query_category: str  # "lexical" or "relationship"
    split: str  # "dev" or "test"
