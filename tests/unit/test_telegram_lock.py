"""M4 unit tests: single-instance guard and technical state retention."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.lock import InstanceLockError, SingleInstanceLock


def test_second_instance_cannot_take_the_lock(tmp_path: Path):
    """architecture.md: two concurrent polling instances are not supported."""
    lock_path = tmp_path / "bot.lock"
    first = SingleInstanceLock(lock_path)
    second = SingleInstanceLock(lock_path)

    first.acquire()
    try:
        with pytest.raises(InstanceLockError):
            second.acquire()
    finally:
        first.release()

    # After release the lock is free again, so a restart succeeds.
    second.acquire()
    second.release()


def test_lock_is_reentrant_within_one_instance(tmp_path: Path):
    """Acquiring twice from the same holder must not deadlock."""
    lock = SingleInstanceLock(tmp_path / "bot.lock")

    lock.acquire()
    lock.acquire()
    lock.release()


def test_context_manager_releases_the_lock(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"

    with SingleInstanceLock(lock_path):
        pass

    other = SingleInstanceLock(lock_path)
    other.acquire()
    other.release()


def test_retention_prune_removes_only_old_rows(tmp_path: Path):
    """C1: the dedup window is bounded, and pruning touches nothing else."""
    db_path = tmp_path / "bot_state.sqlite3"
    state = StateStore(db_path)
    state.mark_update_processed(1, status="sent")
    state.mark_update_processed(2, status="sent")

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE processed_updates SET processed_at = datetime('now', '-30 days') "
        "WHERE update_id = 1"
    )
    conn.commit()
    conn.close()

    removed = state.prune_processed_updates(7)

    assert removed == 1
    assert not state.is_update_processed(1)
    assert state.is_update_processed(2)


def test_non_positive_retention_keeps_every_row(tmp_path: Path):
    """A non-positive retention never deletes state."""
    state = StateStore(tmp_path / "bot_state.sqlite3")
    state.mark_update_processed(5, status="sent")

    assert state.prune_processed_updates(0) == 0
    assert state.is_update_processed(5)


def test_state_stores_only_technical_identifiers(tmp_path: Path):
    """C7: the dedup table has no column able to hold message content."""
    db_path = tmp_path / "bot_state.sqlite3"
    state = StateStore(db_path)
    state.mark_update_processed(7, status="sent")

    conn = sqlite3.connect(str(db_path))
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(processed_updates)")
    }
    conn.close()

    assert columns == {"update_id", "status", "processed_at"}
    assert "text" not in columns
    assert "chat_id" not in columns


def test_update_status_can_be_finalised_after_claim(tmp_path: Path):
    """A claimed update records its truthful final outcome."""
    db_path = tmp_path / "bot_state.sqlite3"
    state = StateStore(db_path)
    state.mark_update_processed(9, status="claimed")

    state.set_update_status(9, "unknown")

    conn = sqlite3.connect(str(db_path))
    status = conn.execute(
        "SELECT status FROM processed_updates WHERE update_id = 9"
    ).fetchone()[0]
    conn.close()
    assert status == "unknown"
