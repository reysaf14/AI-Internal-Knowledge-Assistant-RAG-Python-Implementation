"""Runtime state store for polling offset and idempotency.

SQLite-based state for:
- Telegram polling offset tracking
- Update deduplication (processed update IDs)
- Technical metadata only (NO question/answer/username/chat ID content)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class StateStore:
    """Runtime state persistence (idempotency + polling offset)."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Open connection; creates tables if not exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_updates (
                update_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        return conn

    def get_polling_offset(self) -> int:
        """Get the last processed Telegram update offset."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM runtime_state WHERE key = 'polling_offset'")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def set_polling_offset(self, offset: int) -> None:
        """Update the polling offset after successful processing."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO runtime_state (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                ("polling_offset", str(offset)),
            )
            conn.commit()
        finally:
            conn.close()

    def is_update_processed(self, update_id: int) -> bool:
        """Check if an update has already been processed (deduplication)."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_updates WHERE update_id = ?", (update_id,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def mark_update_processed(self, update_id: int, status: str = "ok") -> None:
        """Mark an update as processed with status."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO processed_updates (update_id, status) "
                "VALUES (?, ?)",
                (update_id, status),
            )
            conn.commit()
        finally:
            conn.close()

    def set_update_status(self, update_id: int, status: str) -> None:
        """Record the final outcome for an update that was already claimed."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE processed_updates SET status = ? WHERE update_id = ?",
                (status, update_id),
            )
            conn.commit()
        finally:
            conn.close()

    def prune_processed_updates(self, retention_days: int) -> int:
        """Delete deduplication rows older than the locked retention window.

        Returns the number of removed rows. Only technical identifiers and a
        timestamp are stored, so pruning can never discard conversation
        content. A non-positive retention keeps all rows.
        """
        if retention_days < 1:
            return 0
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM processed_updates WHERE processed_at < datetime('now', ?)",
                (f"-{int(retention_days)} days",),
            )
            removed = cursor.rowcount
            conn.commit()
            return max(removed, 0)
        finally:
            conn.close()