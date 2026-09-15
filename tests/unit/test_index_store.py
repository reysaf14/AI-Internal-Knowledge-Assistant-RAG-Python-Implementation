"""Unit tests for FTS5 index store (retrieval grounding foundation)."""
from pathlib import Path

import pytest

from rag_assistant.config import AppConfig
from rag_assistant.domain.types import SupportLevel
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.storage.index_store import IndexStore


@pytest.fixture
def built_index(tmp_path: Path, synthetic_docs: Path) -> AppConfig:
    """Build a corpus index and return the config for testing."""
    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    result = rebuild_corpus(cfg)
    assert result.success
    return cfg


def test_index_info(built_index: AppConfig):
    """Index store returns correct metadata."""
    store = IndexStore(built_index.resolve_index_path())
    info = store.get_index_info()
    assert info is not None
    assert info.file_count == 5
    assert info.chunk_count >= 5


def test_search_supported(built_index: AppConfig):
    """Search for a known topic returns results with SUFFICIENT support."""
    store = IndexStore(built_index.resolve_index_path())
    result = store.search("metode pembayaran")
    assert result.support_level == SupportLevel.SUFFICIENT
    assert len(result.chunks) >= 1
    assert any("pembayaran" in c.text.lower() for c in result.chunks)


def test_search_nonexistent_index(tmp_path: Path):
    """Search on missing index returns ERROR."""
    store = IndexStore(tmp_path / "nonexistent.sqlite3")
    result = store.search("test query")
    assert result.support_level == SupportLevel.ERROR


def test_search_chunk_source_files(built_index: AppConfig):
    """Returned chunks have correct source file metadata."""
    store = IndexStore(built_index.resolve_index_path())
    result = store.search("SOP buka toko")
    if result.support_level == SupportLevel.SUFFICIENT:
        for chunk in result.chunks:
            assert chunk.source_file.endswith(".md")
            assert len(chunk.heading_path) > 0