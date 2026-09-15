"""SQLite FTS5 index store for retrieval queries.

Provides read-only access to the active corpus index.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rag_assistant.domain.types import ChunkData, RetrievalResult, SupportLevel


@dataclass(frozen=True)
class IndexInfo:
    """Metadata about the active index."""

    corpus_version: str
    file_count: int
    chunk_count: int


class IndexStore:
    """Read-only access to the active FTS5 corpus index."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Open read-only connection to the index database."""
        if not self._db_path.exists():
            raise FileNotFoundError(f"Index database not found: {self._db_path}")
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_index_info(self) -> IndexInfo | None:
        """Get metadata about the active corpus index."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT corpus_version, file_count, chunk_count FROM corpus_meta LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return IndexInfo(
                    corpus_version=row["corpus_version"],
                    file_count=row["file_count"],
                    chunk_count=row["chunk_count"],
                )
            return None
        except Exception:  # noqa: BLE001 - missing/corrupt index is reported as no info
            return None

    def search(self, query: str, limit: int = 5) -> RetrievalResult:
        """Full-text search against corpus index.

        The external query is tokenized before it reaches FTS5.  This prevents
        FTS operators, quotes, or punctuation in a user question from changing
        the query grammar.  Results are ranked by FTS5 relevance with a stable
        chunk-id tie-breaker.  The support gate is applied by the retrieval
        service; this low-level method only reports whether FTS returned rows.
        """
        from rag_assistant.retrieval.query import normalize_query

        normalized = normalize_query(query)
        if not normalized.is_valid or not normalized.terms:
            return RetrievalResult(support_level=SupportLevel.INSUFFICIENT)
        return self.search_terms(normalized.terms, limit=limit)

    def search_terms(
        self, terms: Sequence[str], limit: int = 5
    ) -> RetrievalResult:
        """Search using already normalized terms.

        ``search_terms`` is the boundary used by :class:`Retriever`.  Terms
        are normalized again defensively, then bound as one SQL parameter; no
        external text is interpolated into SQL or an FTS command string.
        """
        from rag_assistant.retrieval.query import (
            build_fts_match_query,
            normalize_terms,
        )

        normalized_terms = normalize_terms(terms)
        if not normalized_terms or not isinstance(limit, int) or limit <= 0:
            return RetrievalResult(support_level=SupportLevel.INSUFFICIENT)

        if not self._db_path.exists():
            return RetrievalResult(support_level=SupportLevel.ERROR, corpus_version="")

        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT corpus_version FROM corpus_meta LIMIT 1")
                meta = cursor.fetchone()
                corpus_version = meta["corpus_version"] if meta else ""

                cursor.execute(
                    """
                    SELECT c.chunk_id, c.text, c.source_file, c.heading_path,
                    c.corpus_version
                    FROM corpus_fts f
                    JOIN corpus_chunks c ON f.chunk_id = c.chunk_id
                    WHERE corpus_fts MATCH ?
                    ORDER BY f.rank ASC, c.chunk_id ASC
                    LIMIT ?
                    """,
                    (build_fts_match_query(normalized_terms), limit),
                )
                chunks = [
                    ChunkData(
                        chunk_id=row["chunk_id"],
                        text=row["text"],
                        source_file=row["source_file"],
                        heading_path=row["heading_path"],
                        corpus_version=row["corpus_version"],
                    )
                    for row in cursor.fetchall()
                ]

            support = (
                SupportLevel.SUFFICIENT if chunks else SupportLevel.INSUFFICIENT
            )
            return RetrievalResult(
                chunks=chunks,
                support_level=support,
                corpus_version=corpus_version,
            )

        except Exception:  # noqa: BLE001 - query failure surfaces as ERROR, never fake success
            return RetrievalResult(support_level=SupportLevel.ERROR, corpus_version="")
