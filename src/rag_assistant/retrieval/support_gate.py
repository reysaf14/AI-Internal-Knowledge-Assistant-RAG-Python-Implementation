"""High-precision lexical support gate for retrieval candidates."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from rag_assistant.domain.types import ChunkData, SupportLevel
from rag_assistant.retrieval.query import matched_query_terms, normalize_terms


@dataclass(frozen=True)
class ChunkMatch:
    """A candidate chunk annotated with lexical evidence for the query."""

    chunk: ChunkData
    matched_terms: tuple[str, ...]
    coverage: float
    source_rank: int


@dataclass(frozen=True)
class SupportDecision:
    """Support-gate decision and the chunks safe to pass downstream."""

    support_level: SupportLevel
    matches: tuple[ChunkMatch, ...] = ()
    matched_terms: tuple[str, ...] = ()
    coverage: float = 0.0
    reason: str = ""

    @property
    def chunks(self) -> tuple[ChunkData, ...]:
        """Return only chunks that satisfy the support gate."""
        return tuple(match.chunk for match in self.matches)


class SupportGate:
    """Require enough query-bearing terms before context is considered safe.

    Calibrated M2 defaults are intentionally high precision: at least two
    matched terms and 100% query-term coverage for multi-term queries.
    A single non-boilerplate term is accepted only when it has at least three
    characters.  This gate is lexical and corpus-size independent; the
    approved 12+3 evaluation remains the later calibration check.
    """

    def __init__(
        self,
        min_matched_terms: int = 2,
        min_coverage: float = 1.0,
        min_single_term_length: int = 3,
    ) -> None:
        if min_matched_terms < 1:
            raise ValueError("min_matched_terms must be positive")
        if not 0 < min_coverage <= 1:
            raise ValueError("min_coverage must be in (0, 1]")
        if min_single_term_length < 1:
            raise ValueError("min_single_term_length must be positive")
        self.min_matched_terms = min_matched_terms
        self.min_coverage = min_coverage
        self.min_single_term_length = min_single_term_length

    def evaluate(
        self, query_terms: Sequence[str], candidates: Sequence[ChunkData]
    ) -> SupportDecision:
        """Classify candidates and retain only evidence-bearing chunks."""
        terms = normalize_terms(query_terms)
        if not terms:
            return SupportDecision(
                support_level=SupportLevel.INSUFFICIENT,
                reason="no_search_terms",
            )
        if not candidates:
            return SupportDecision(
                support_level=SupportLevel.INSUFFICIENT,
                reason="no_candidates",
            )

        matches: list[ChunkMatch] = []
        for source_rank, chunk in enumerate(candidates):
            matched = matched_query_terms(
                terms, f"{chunk.heading_path} {chunk.text}"
            )
            coverage = len(matched) / len(terms)
            required = self._required_matches(terms)
            if len(matched) >= required and coverage >= self.min_coverage:
                matches.append(
                    ChunkMatch(
                        chunk=chunk,
                        matched_terms=matched,
                        coverage=coverage,
                        source_rank=source_rank,
                    )
                )

        matches.sort(
            key=lambda item: (
                -len(item.matched_terms),
                -item.coverage,
                item.source_rank,
                item.chunk.chunk_id,
            )
        )
        if not matches:
            return SupportDecision(
                support_level=SupportLevel.INSUFFICIENT,
                reason="insufficient_term_coverage",
            )

        best = matches[0]
        return SupportDecision(
            support_level=SupportLevel.SUFFICIENT,
            matches=tuple(matches),
            matched_terms=best.matched_terms,
            coverage=best.coverage,
            reason="term_coverage_sufficient",
        )

    def _required_matches(self, terms: tuple[str, ...]) -> int:
        if len(terms) == 1:
            return 1 if len(terms[0]) >= self.min_single_term_length else 2
        return max(
            self.min_matched_terms,
            math.ceil(len(terms) * self.min_coverage),
        )
