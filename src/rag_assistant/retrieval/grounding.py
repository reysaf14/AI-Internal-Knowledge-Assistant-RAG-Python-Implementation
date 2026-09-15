"""Context and source allowlisting for the future answering boundary."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePath

from rag_assistant.domain.types import ChunkData, RetrievalResult, SupportLevel


@dataclass(frozen=True)
class GroundedContext:
    """Validated context and source metadata derived only from index chunks."""

    chunks: tuple[ChunkData, ...]
    sources: tuple[str, ...]
    corpus_version: str


@dataclass(frozen=True)
class GroundingResult:
    """Fail-closed result of context validation."""

    valid: bool
    context: GroundedContext | None = None
    reason: str = ""


@dataclass(frozen=True)
class SourceValidation:
    """Allowlist result for source names proposed by an answerer."""

    valid: bool
    accepted_sources: tuple[str, ...] = ()
    rejected_sources: tuple[str, ...] = ()
    allowed_sources: tuple[str, ...] = ()
    reason: str = ""


def build_grounded_context(
    result: RetrievalResult, max_chunks: int = 5
) -> GroundingResult:
    """Validate retrieval output before it can be passed to a model.

    Unsupported/error results never expose candidate chunks downstream.  The
    checks also ensure all chunks belong to one active corpus and carry only a
    basename source ending in ``.md``.
    """
    if result.support_level != SupportLevel.SUFFICIENT:
        return GroundingResult(valid=False, reason="retrieval_not_sufficient")
    if not isinstance(max_chunks, int) or max_chunks < 1:
        return GroundingResult(valid=False, reason="invalid_context_limit")
    if not result.corpus_version or not result.chunks:
        return GroundingResult(valid=False, reason="empty_context")

    chunks = tuple(result.chunks[:max_chunks])
    if not chunks:
        return GroundingResult(valid=False, reason="empty_context")

    chunk_ids: set[str] = set()
    sources: list[str] = []
    seen_sources: set[str] = set()
    for chunk in chunks:
        if not _valid_chunk(chunk, result.corpus_version, chunk_ids):
            return GroundingResult(valid=False, reason="invalid_context_chunk")
        chunk_ids.add(chunk.chunk_id)
        if chunk.source_file not in seen_sources:
            seen_sources.add(chunk.source_file)
            sources.append(chunk.source_file)

    return GroundingResult(
        valid=True,
        context=GroundedContext(
            chunks=chunks,
            sources=tuple(sources),
            corpus_version=result.corpus_version,
        ),
    )


def validate_source_claims(
    claimed_sources: str | Iterable[str],
    context: GroundedContext | GroundingResult | RetrievalResult | Sequence[ChunkData],
) -> SourceValidation:
    """Accept only exact source names present in validated retrieval context."""
    allowed = _allowed_sources(context)
    claims = _unique_sources((claimed_sources,) if isinstance(claimed_sources, str) else claimed_sources)
    if not claims:
        return SourceValidation(
            valid=False,
            allowed_sources=allowed,
            reason="no_source_claim",
        )

    rejected = tuple(source for source in claims if source not in allowed)
    if rejected:
        return SourceValidation(
            valid=False,
            rejected_sources=rejected,
            allowed_sources=allowed,
            reason="source_outside_context",
        )

    return SourceValidation(
        valid=True,
        accepted_sources=claims,
        allowed_sources=allowed,
        reason="sources_in_context",
    )


def _valid_chunk(
    chunk: ChunkData, corpus_version: str, chunk_ids: set[str]
) -> bool:
    source = chunk.source_file
    return bool(
        chunk.chunk_id
        and chunk.chunk_id not in chunk_ids
        and chunk.text.strip()
        and chunk.heading_path.strip()
        and source
        and source == PurePath(source).name
        and "/" not in source
        and "\\" not in source
        and source.casefold().endswith(".md")
        and chunk.corpus_version == corpus_version
    )


def _allowed_sources(
    context: GroundedContext | GroundingResult | RetrievalResult | Sequence[ChunkData],
) -> tuple[str, ...]:
    if isinstance(context, GroundingResult):
        if not context.valid or context.context is None:
            return ()
        return context.context.sources
    if isinstance(context, GroundedContext):
        return context.sources
    if isinstance(context, RetrievalResult):
        if context.support_level != SupportLevel.SUFFICIENT:
            return ()
        chunks = context.chunks
    else:
        chunks = context
    return _unique_sources(chunk.source_file for chunk in chunks if chunk.source_file)


def _unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, str):
            continue
        normalized = source.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)
