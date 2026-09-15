"""Safe, deterministic normalization for user text before SQLite FTS5."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# These are question scaffolding or corpus-wide boilerplate terms.  Removing
# them keeps the support gate focused on policy-bearing terms.  Domain terms
# such as ``hari`` and ``lokasi`` are intentionally retained.
_STOPWORDS = frozenset(
    {
        "ada",
        "akan",
        "apa",
        "apakah",
        "bagaimana",
        "bagi",
        "berikut",
        "berapa",
        "bisa",
        "boleh",
        "dapat",
        "dan",
        "dengan",
        "di",
        "dari",
        "dimana",
        "ini",
        "itu",
        "kah",
        "ke",
        "kapan",
        "kami",
        "mana",
        "mengenai",
        "menurut",
        "near",
        "not",
        "or",
        "pada",
        "saja",
        "saya",
        "tentang",
        "tersebut",
        "tidak",
        "toko",
        "untuk",
        "yang",
    }
)


@dataclass(frozen=True)
class NormalizedQuery:
    """Normalized query terms, without retaining the original user text."""

    terms: tuple[str, ...] = ()
    is_valid: bool = True


def tokenize_text(value: str) -> tuple[str, ...]:
    """Return unique, case-folded Unicode word tokens in source order."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(normalized):
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tuple(tokens)


def normalize_terms(terms: Iterable[str]) -> tuple[str, ...]:
    """Normalize arbitrary term input and remove FTS grammar characters."""
    result: list[str] = []
    seen: set[str] = set()
    for value in terms:
        if not isinstance(value, str):
            continue
        for token in tokenize_text(value):
            if token in _STOPWORDS or len(token) < 2 or token in seen:
                continue
            seen.add(token)
            result.append(token)
    return tuple(result)


def normalize_query(query: str, max_chars: int = 2000) -> NormalizedQuery:
    """Normalize a question for retrieval without preserving its payload."""
    if not isinstance(query, str) or max_chars <= 0:
        return NormalizedQuery(is_valid=False)

    normalized = unicodedata.normalize("NFKC", query)
    if len(normalized) > max_chars:
        return NormalizedQuery(is_valid=False)

    return NormalizedQuery(terms=normalize_terms(tokenize_text(normalized)))


def build_fts_match_query(terms: Iterable[str]) -> str:
    """Build a literal OR query safe for the FTS5 MATCH grammar."""
    normalized_terms = normalize_terms(terms)
    # Terms are tokenized above, but doubling quotes is a defensive invariant
    # if this helper is reused with a future tokenizer.
    return " OR ".join(
        f'"{term.replace(chr(34), chr(34) * 2)}"' for term in normalized_terms
    )


def matched_query_terms(query_terms: Iterable[str], text: str) -> tuple[str, ...]:
    """Return query terms occurring exactly in a chunk's text or headings."""
    document_terms = set(tokenize_text(text))
    return tuple(term for term in normalize_terms(query_terms) if term in document_terms)
