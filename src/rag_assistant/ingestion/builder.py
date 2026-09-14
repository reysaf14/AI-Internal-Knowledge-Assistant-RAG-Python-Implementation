"""Corpus rebuild: full rebuild with validation and atomic activation.

Strategy:
1. Inventory: validate exactly N official files (00-25; default 26 for local/vps,
   lower for synthetic test fixtures)
2. Parse: read and split each file into heading-aware sections
3. Chunk: generate chunks with source metadata
4. Version: compute deterministic corpus_version
5. Index: write chunks to new SQLite FTS5 database
6. Validate: ensure new index has expected count
7. Activate: atomically swap new index as active

If any step fails, the existing active index remains unchanged (fail-closed).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from rag_assistant.config import AppConfig
from rag_assistant.domain.types import ChunkData, CorpusBuildResult
from rag_assistant.ingestion.chunking import generate_chunks
from rag_assistant.ingestion.inventory import scan_corpus
from rag_assistant.ingestion.parser import parse_markdown
from rag_assistant.ingestion.versioning import compute_corpus_version

logger = logging.getLogger("rag_assistant.ingestion")

# Chunk bound defaults: minimum 1 chunk per corpus file, generous upper bound.
# For a 26-file corpus this means min 26 / max 500 chunks.
def _chunk_bounds(expected_file_count: int) -> tuple[int, int]:
    return max(1, expected_file_count), max(expected_file_count * 20, 500)


def _create_index_db(db_path: Path, chunks: list[ChunkData], corpus_version: str) -> None:
    """Create a new SQLite database with FTS5 index for chunks."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS corpus_meta (
                corpus_version TEXT PRIMARY KEY,
                file_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS corpus_chunks (
                chunk_id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                source_file TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                corpus_version TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                heading_path,
                source_file UNINDEXED,
                corpus_version UNINDEXED,
                content=corpus_chunks,
                content_rowid=rowid
            )
            """
        )

        cursor.execute(
            "INSERT INTO corpus_meta (corpus_version, file_count, chunk_count) "
            "VALUES (?, ?, ?)",
            (
                corpus_version,
                len({c.source_file for c in chunks}),
                len(chunks),
            ),
        )

        for chunk in chunks:
            cursor.execute(
                "INSERT INTO corpus_chunks "
                "(chunk_id, text, source_file, heading_path, corpus_version) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.text,
                    chunk.source_file,
                    chunk.heading_path,
                    chunk.corpus_version,
                ),
            )

        cursor.execute("INSERT INTO corpus_fts(corpus_fts) VALUES('rebuild')")
        conn.commit()
    finally:
        conn.close()


def _validate_index(
    db_path: Path,
    expected_file_count: int,
    expected_chunk_count: int,
    corpus_version: str,
) -> bool:
    """Validate a freshly created index database."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT corpus_version, file_count, chunk_count FROM corpus_meta LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            logger.error("Index validation failed: no metadata found")
            return False

        db_version, db_file_count, db_chunk_count = row
        if db_version != corpus_version:
            logger.error(
                f"Index validation failed: version mismatch {db_version} != {corpus_version}"
            )
            return False
        if db_file_count != expected_file_count:
            logger.error(
                f"Index validation failed: file count {db_file_count} != {expected_file_count}"
            )
            return False
        if db_chunk_count != expected_chunk_count:
            logger.error(
                f"Index validation failed: chunk count {db_chunk_count} != {expected_chunk_count}"
            )
            return False

        cursor.execute("SELECT COUNT(*) FROM corpus_fts")
        fts_count = cursor.fetchone()[0]
        if fts_count != expected_chunk_count:
            logger.error(
                f"Index validation failed: FTS count {fts_count} != expected {expected_chunk_count}"
            )
            return False

        return True
    except Exception as exc:  # noqa: BLE001 - fail-closed: validation error aborts rebuild
        logger.error(f"Index validation error: {exc}")
        return False
    finally:
        conn.close()


def _activate_index(temp_db: Path, target_db: Path) -> None:
    """Atomically activate new index by renaming temp -> target.

    Strategy: backup existing target to .bak, rename temp to target, remove backup.
    """
    backup_path = target_db.with_suffix(".sqlite3.bak")

    if backup_path.exists():
        backup_path.unlink()

    if target_db.exists():
        target_db.rename(backup_path)

    temp_db.rename(target_db)

    if backup_path.exists():
        backup_path.unlink()


def rebuild_corpus(cfg: AppConfig) -> CorpusBuildResult:
    """Full corpus rebuild: inventory -> parse -> chunk -> version -> index -> activate.

    Primary M1 operation. Processes all official documents and creates a new FTS5
    index. If any step fails, the existing index remains active (fail-closed).
    """
    docs_dir = cfg.resolve_docs_path()
    index_path = cfg.resolve_index_path()

    logger.info("Step 1: Scanning corpus inventory")
    inventory = scan_corpus(docs_dir, expected_file_count=cfg.expected_file_count)
    if not inventory.is_valid:
        error_msg = "; ".join(inventory.errors)
        logger.error(f"Inventory failed: {error_msg}")
        return CorpusBuildResult(
            corpus_version="",
            file_count=0,
            chunk_count=0,
            success=False,
            error_message=f"Inventory failed: {error_msg}",
        )

    logger.info(f"Step 2: Parsing {len(inventory.items)} files")
    all_chunks: list[ChunkData] = []
    file_contents: list[tuple[str, str]] = []

    for item in inventory.items:
        filepath = docs_dir / item.filename
        try:
            content = filepath.read_text(encoding="utf-8")
            file_contents.append((item.filename, content))
            doc = parse_markdown(filepath, item.relative_path)
            all_chunks.extend(generate_chunks(doc, "PENDING_VERSION"))
        except Exception as exc:  # noqa: BLE001 - fail-closed: unreadable/invalid file aborts rebuild
            error_msg = f"Failed to parse {item.filename}: {exc}"
            logger.error(error_msg)
            return CorpusBuildResult(
                corpus_version="",
                file_count=0,
                chunk_count=0,
                success=False,
                error_message=error_msg,
            )

    logger.info("Step 3: Computing corpus version")
    corpus_version = compute_corpus_version(file_contents)

    # Rebuild chunks with real corpus_version
    all_chunks = []
    for item in inventory.items:
        filepath = docs_dir / item.filename
        try:
            doc = parse_markdown(filepath, item.relative_path)
            all_chunks.extend(generate_chunks(doc, corpus_version))
        except Exception as exc:  # noqa: BLE001 - fail-closed: chunking error aborts rebuild
            error_msg = f"Failed to chunk {item.filename}: {exc}"
            logger.error(error_msg)
            return CorpusBuildResult(
                corpus_version="",
                file_count=0,
                chunk_count=0,
                success=False,
                error_message=error_msg,
            )

    logger.info(f"Generated {len(all_chunks)} chunks from {len(inventory.items)} files")

    min_chunks, max_chunks = _chunk_bounds(cfg.expected_file_count)

    if len(all_chunks) < min_chunks:
        return CorpusBuildResult(
            corpus_version=corpus_version,
            file_count=len(inventory.items),
            chunk_count=len(all_chunks),
            success=False,
            error_message=f"Too few chunks: {len(all_chunks)} < {min_chunks}",
        )
    if len(all_chunks) > max_chunks:
        return CorpusBuildResult(
            corpus_version=corpus_version,
            file_count=len(inventory.items),
            chunk_count=len(all_chunks),
            success=False,
            error_message=f"Too many chunks: {len(all_chunks)} > {max_chunks}",
        )

    logger.info("Step 6: Writing index to temporary database")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3", dir=str(index_path.parent))
    os.close(tmp_fd)
    temp_db = Path(tmp_path)

    try:
        _create_index_db(temp_db, all_chunks, corpus_version)

        logger.info("Step 7: Validating new index")
        if not _validate_index(
            temp_db, len(inventory.items), len(all_chunks), corpus_version
        ):
            temp_db.unlink(missing_ok=True)
            return CorpusBuildResult(
                corpus_version=corpus_version,
                file_count=len(inventory.items),
                chunk_count=len(all_chunks),
                success=False,
                error_message="Index validation failed",
            )

        logger.info("Step 8: Activating new index")
        _activate_index(temp_db, index_path)

        result = CorpusBuildResult(
            corpus_version=corpus_version,
            file_count=len(inventory.items),
            chunk_count=len(all_chunks),
            success=True,
        )
        logger.info(f"Corpus rebuild successful: {result}")
        return result

    except Exception as exc:  # noqa: BLE001 - fail-closed: unlink temp index and abort
        temp_db.unlink(missing_ok=True)
        error_msg = f"Rebuild failed during indexing: {exc}"
        logger.error(error_msg)
        return CorpusBuildResult(
            corpus_version=corpus_version,
            file_count=len(inventory.items),
            chunk_count=len(all_chunks),
            success=False,
            error_message=error_msg,
        )