"""M1 interruption proof for the temporary-index activation boundary."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rag_assistant.config import AppConfig
from rag_assistant.ingestion import builder
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.storage.index_store import IndexStore


def _cfg(tmp_path: Path, docs_path: Path) -> AppConfig:
    return AppConfig(
        app_env="test",
        docs_path=docs_path,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )


def test_interruption_during_candidate_write_preserves_active_index(
    tmp_path: Path, synthetic_docs: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC-004/G1: an interrupted candidate never replaces the active index."""
    cfg = _cfg(tmp_path, synthetic_docs)
    first = rebuild_corpus(cfg)
    assert first.success

    index_path = cfg.resolve_index_path()

    def interrupted_writer(
        db_path: Path, _chunks: list[object], _corpus_version: str
    ) -> None:
        # Leave a deliberately incomplete candidate on disk, then simulate a
        # process cancellation before validation or activation can run.
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE partial_candidate (marker TEXT)")
            conn.execute("INSERT INTO partial_candidate VALUES ('interrupted')")
            conn.commit()
        finally:
            conn.close()
        raise KeyboardInterrupt("injected candidate-write interruption")

    monkeypatch.setattr(builder, "_create_index_db", interrupted_writer)

    with pytest.raises(KeyboardInterrupt, match="injected candidate-write"):
        rebuild_corpus(cfg)

    active = IndexStore(index_path)
    info = active.get_index_info()
    assert info is not None
    assert info.corpus_version == first.corpus_version
    assert info.file_count == first.file_count
    assert info.chunk_count == first.chunk_count
    assert not [
        candidate
        for candidate in index_path.parent.glob("*.sqlite3")
        if candidate != index_path
    ]
