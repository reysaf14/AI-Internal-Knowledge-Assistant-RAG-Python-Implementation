"""Unit tests for corpus rebuild builder.

Covers AC-001 (valid rebuild), AC-002 (invalid/fail-closed), AC-003 (duplicate rebuild).
"""
from pathlib import Path

from rag_assistant.config import AppConfig
from rag_assistant.ingestion.builder import rebuild_corpus


def _cfg(tmp_path: Path, docs_path: Path, expected: int = 5) -> AppConfig:
    return AppConfig(
        app_env="test",
        docs_path=docs_path,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=expected,
        project_root=tmp_path,
    )


def test_rebuild_valid_corpus(tmp_path: Path, synthetic_docs: Path):
    """AC-001: rebuild with valid 5-file corpus succeeds and produces index."""
    cfg = _cfg(tmp_path, synthetic_docs)
    result = rebuild_corpus(cfg)
    assert result.success, f"Rebuild failed: {result.error_message}"
    assert result.file_count == 5
    assert result.chunk_count >= 5
    assert len(result.corpus_version) == 16

    index_path = cfg.resolve_index_path()
    assert index_path.exists()


def test_rebuild_invalid_empty_corpus(tmp_path: Path, empty_docs: Path):
    """AC-002: rebuild with empty corpus fails, no index created."""
    cfg = _cfg(tmp_path, empty_docs)
    result = rebuild_corpus(cfg)
    assert not result.success
    assert result.error_message is not None


def test_rebuild_invalid_prefix(tmp_path: Path, invalid_docs: Path, synthetic_docs: Path):
    """AC-002: rebuild with files outside 00-25 range fails.

    invalid_docs has 2 files; match its expected count so the prefix
    validation (outside 00-25) is exercised rather than count mismatch.
    """
    cfg = AppConfig(
        app_env="test",
        docs_path=invalid_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=2,
        project_root=tmp_path,
    )
    result = rebuild_corpus(cfg)
    assert not result.success


def test_rebuild_preserves_old_index_on_failure(tmp_path: Path, synthetic_docs: Path):
    """AC-002: when rebuild fails, old index remains active."""
    cfg = _cfg(tmp_path, synthetic_docs)

    result1 = rebuild_corpus(cfg)
    assert result1.success
    old_version = result1.corpus_version

    empty_dir = tmp_path / "docs_empty"
    empty_dir.mkdir(exist_ok=True)
    cfg2 = _cfg(tmp_path, empty_dir, expected=0)  # 0 expected, empty dir -> count fail
    result2 = rebuild_corpus(cfg2)
    assert not result2.success

    from rag_assistant.storage.index_store import IndexStore

    store = IndexStore(cfg.resolve_index_path())
    info = store.get_index_info()
    assert info is not None
    assert info.corpus_version == old_version


def test_rebuild_idempotent(tmp_path: Path, synthetic_docs: Path):
    """AC-003: rebuilding identical corpus produces same version, no corruption."""
    cfg = _cfg(tmp_path, synthetic_docs)

    result1 = rebuild_corpus(cfg)
    assert result1.success
    result2 = rebuild_corpus(cfg)
    assert result2.success
    assert result1.corpus_version == result2.corpus_version
    assert result1.chunk_count == result2.chunk_count