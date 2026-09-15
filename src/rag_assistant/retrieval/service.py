"""Retrieval orchestration: safe query, FTS ranking, and support gating."""
from __future__ import annotations

from dataclasses import dataclass

from rag_assistant.domain.types import RetrievalResult, SupportLevel
from rag_assistant.retrieval.query import normalize_query
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore


@dataclass(frozen=True)
class RetrievalPolicy:
    """M2 retrieval parameters locked before approved eval calibration."""

    candidate_limit: int = 20
    context_limit: int = 5
    min_matched_terms: int = 2
    min_coverage: float = 1.0
    min_single_term_length: int = 3

    def __post_init__(self) -> None:
        if self.candidate_limit < 1 or self.context_limit < 1:
            raise ValueError("retrieval limits must be positive")


class Retriever:
    """Return only context that passes the support gate."""

    def __init__(
        self,
        index_store: IndexStore,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        self._index_store = index_store
        self.policy = policy or RetrievalPolicy()
        self._support_gate = SupportGate(
            min_matched_terms=self.policy.min_matched_terms,
            min_coverage=self.policy.min_coverage,
            min_single_term_length=self.policy.min_single_term_length,
        )

    def retrieve(self, query: str) -> RetrievalResult:
        """Search the active index and fail closed when support is weak."""
        normalized = normalize_query(query)
        if not normalized.is_valid or not normalized.terms:
            return RetrievalResult(support_level=SupportLevel.INSUFFICIENT)

        candidates = self._index_store.search_terms(
            normalized.terms, limit=self.policy.candidate_limit
        )
        if candidates.support_level == SupportLevel.ERROR:
            return candidates

        decision = self._support_gate.evaluate(normalized.terms, candidates.chunks)
        if decision.support_level != SupportLevel.SUFFICIENT:
            return RetrievalResult(
                support_level=SupportLevel.INSUFFICIENT,
                corpus_version=candidates.corpus_version,
            )

        return RetrievalResult(
            chunks=list(decision.chunks[: self.policy.context_limit]),
            support_level=SupportLevel.SUFFICIENT,
            corpus_version=candidates.corpus_version,
        )


RetrievalService = Retriever
