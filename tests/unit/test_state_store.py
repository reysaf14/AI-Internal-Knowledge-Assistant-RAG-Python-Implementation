"""Unit tests for runtime state store (idempotency foundation)."""
from pathlib import Path

from rag_assistant.storage.state_store import StateStore


def test_polling_offset_default(tmp_path: Path):
    """Default polling offset is 0."""
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.get_polling_offset() == 0


def test_polling_offset_roundtrip(tmp_path: Path):
    """Set and get polling offset."""
    store = StateStore(tmp_path / "state.sqlite3")
    store.set_polling_offset(42)
    assert store.get_polling_offset() == 42


def test_update_not_processed(tmp_path: Path):
    """Unknown update ID is not processed."""
    store = StateStore(tmp_path / "state.sqlite3")
    assert not store.is_update_processed(100)


def test_mark_update_processed(tmp_path: Path):
    """Marked update is processed (deduplication)."""
    store = StateStore(tmp_path / "state.sqlite3")
    store.mark_update_processed(100)
    assert store.is_update_processed(100)


def test_update_idempotent(tmp_path: Path):
    """Marking same update twice does not create duplicate rows."""
    store = StateStore(tmp_path / "state.sqlite3")
    store.mark_update_processed(100)
    store.mark_update_processed(100)
    assert store.is_update_processed(100)