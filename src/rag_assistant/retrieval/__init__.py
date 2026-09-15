"""Retrieval and source-grounding boundaries for the active corpus index."""

from rag_assistant.retrieval.grounding import (
    GroundedContext,
    GroundingResult,
    SourceValidation,
    build_grounded_context,
    validate_source_claims,
)
from rag_assistant.retrieval.query import NormalizedQuery, normalize_query
from rag_assistant.retrieval.service import RetrievalPolicy, Retriever
from rag_assistant.retrieval.support_gate import (
    ChunkMatch,
    SupportDecision,
    SupportGate,
)

__all__ = [
    "ChunkMatch",
    "GroundedContext",
    "GroundingResult",
    "NormalizedQuery",
    "RetrievalPolicy",
    "Retriever",
    "SourceValidation",
    "SupportDecision",
    "SupportGate",
    "build_grounded_context",
    "normalize_query",
    "validate_source_claims",
]
