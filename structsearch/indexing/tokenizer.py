"""Identifier-aware tokenizer shared by indexing and query handling.

snake_case, camelCase, PascalCase and acronyms are split into lowercase subwords:
  validate_user_input -> validate user input
  FileNotFoundError   -> file found error   ('not' is a stopword)
  HTTPServer          -> http server
Stopwords, single characters and pure numbers are dropped. There is no stemming
(documented limitation: 'validate' does not match 'validation').
"""
from __future__ import annotations

import re
from typing import Iterable, List

_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Function words plus Python words that carry no retrieval signal.
STOPWORDS = frozenset(
    """a an the of to in on at by for from with and or not is are was were be been as it its
    this that these those if then than but so into over per self cls""".split()
)

# Extra words dropped from queries only (query phrasing, not code vocabulary).
QUERY_STOPWORDS = frozenset(
    """find show search give me all any what which where who how do does can should please
    function functions method methods code""".split()
)


def split_identifier(text: str) -> List[str]:
    """Split one identifier or phrase into lowercase subwords (no filtering)."""
    text = _CAMEL_ACRONYM.sub(r"\1 \2", text)
    text = _CAMEL_BOUNDARY.sub(r"\1 \2", text)
    return [part.lower() for part in _NON_ALNUM.split(text) if part]


def _keep(token: str) -> bool:
    return len(token) >= 2 and not token.isdigit() and token not in STOPWORDS


def tokenize_words(words: Iterable[str]) -> List[str]:
    """Tokenize already-extracted words or identifiers."""
    out: List[str] = []
    for word in words:
        out.extend(tok for tok in split_identifier(word) if _keep(tok))
    return out


def tokenize_text(text: str) -> List[str]:
    """Tokenize free text or source code."""
    return tokenize_words(WORD_RE.findall(text))


def tokenize_query(query: str) -> List[str]:
    return [tok for tok in tokenize_text(query) if tok not in QUERY_STOPWORDS]
