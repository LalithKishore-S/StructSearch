"""Build TextRecords (the text view of a CodeUnit)."""
from __future__ import annotations

import ast
import io
import keyword
import re
import tokenize
from typing import Iterable, List

from structsearch.indexing.tokenizer import WORD_RE
from structsearch.ingestion.segmenter import parse_unit
from structsearch.schemas import PARSEABLE, CodeUnit, TextRecord

_KEYWORDS = frozenset(keyword.kwlist)
_COMMENT_RE = re.compile(r"#\s*(.*)$")
_DUP_SUFFIX = re.compile(r"#\d+$")


def _display_name(unit: CodeUnit) -> str:
    """Qualified name (Class.method) for functions; file stem for file-level units."""
    qual = _DUP_SUFFIX.sub("", unit.unit_id.split("::", 1)[-1])
    return unit.name if qual == "<module>" else qual


def _comments_tokenize(source: str) -> str:
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            text = tok.string.lstrip("#").strip()
            if text:
                found.append(text)
    return "\n".join(found)


def _comments_regex(source: str) -> str:
    """Fallback for code the tokenizer rejects. May also catch '#' inside strings."""
    found = []
    for line in source.split("\n"):
        match = _COMMENT_RE.search(line)
        if match and match.group(1):
            found.append(match.group(1))
    return "\n".join(found)


def _comments(source: str) -> str:
    try:
        return _comments_tokenize(source)
    except (tokenize.TokenError, SyntaxError):
        return _comments_regex(source)


def _regex_identifiers(source: str) -> List[str]:
    return list(dict.fromkeys(w for w in WORD_RE.findall(source) if w not in _KEYWORDS))


def _ast_identifiers(node: ast.AST) -> List[str]:
    names: List[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.append(n.id)
        elif isinstance(n, ast.Attribute):
            names.append(n.attr)
        elif isinstance(n, ast.arg):
            names.append(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            names.append(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            names.append(n.name)
        elif isinstance(n, ast.alias):
            names.append(n.asname or n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.append(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.extend(n.names)
    return list(dict.fromkeys(names))


def build_text_record(unit: CodeUnit) -> TextRecord:
    """Text view of one unit.

    identifiers: names used in the code (from the AST when the unit parsed, else a
                 regex over the source minus Python keywords).
    docstring_comments: docstring plus comments.
    code_tokens: every word in the source, keywords and string-literal words included.
    """
    source = unit.source_text
    identifiers: List[str] = []
    docstring = ""
    comments = ""
    parsed = False
    if unit.parse_status in PARSEABLE:
        try:
            node = parse_unit(unit)
            identifiers = _ast_identifiers(node)
            docstring = ast.get_docstring(node) or ""
            comments = _comments(source)
            parsed = True
        except (SyntaxError, ValueError):
            parsed = False
    if not parsed:
        identifiers = _regex_identifiers(source)
        comments = _comments_regex(source)
        docstring = ""
    return TextRecord(
        unit_id=unit.unit_id,
        name=_display_name(unit),
        identifiers=identifiers,
        docstring_comments="\n".join(p for p in (docstring, comments) if p),
        code_tokens=WORD_RE.findall(source),
    )


def build_text_records(units: Iterable[CodeUnit]) -> List[TextRecord]:
    return [build_text_record(u) for u in units]
