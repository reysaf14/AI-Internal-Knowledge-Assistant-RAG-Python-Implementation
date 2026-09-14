"""Core domain types and result containers.

All types are immutable dataclasses. No Telegram/payload data is stored here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SupportLevel(Enum):
    """Retrieval support classification."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    ERROR = "error"


@dataclass(frozen=True)
class ChunkData:
    """A single document chunk with source metadata."""

    chunk_id: str
    text: str
    source_file: str
    heading_path: str
    corpus_version: str


@dataclass(frozen=True)
class CorpusBuildResult:
    """Result of a corpus rebuild operation."""

    corpus_version: str
    file_count: int
    chunk_count: int
    success: bool
    error_message: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    """Result of a retrieval search query."""

    chunks: list[ChunkData] = field(default_factory=list)
    support_level: SupportLevel = SupportLevel.INSUFFICIENT
    corpus_version: str = ""


@dataclass(frozen=True)
class AnswerResult:
    """Final answer to present to user."""

    text: str
    sources: list[str] = field(default_factory=list)
    supported: bool = False
    abstained: bool = False