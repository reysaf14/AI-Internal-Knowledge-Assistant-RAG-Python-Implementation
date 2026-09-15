"""Unit tests for chunk generation."""
from pathlib import Path

from rag_assistant.ingestion.chunking import generate_chunks
from rag_assistant.ingestion.parser import parse_markdown


def test_chunks_from_document(synthetic_docs: Path):
    """Chunks are generated from parsed sections."""
    doc = parse_markdown(
        synthetic_docs / "00_Profil_Perusahaan.md", "docs/00_Profil_Perusahaan.md"
    )
    chunks = generate_chunks(doc, corpus_version="test_v1")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.source_file == "00_Profil_Perusahaan.md"
        assert chunk.corpus_version == "test_v1"
        assert len(chunk.text) > 0


def test_chunk_ids_are_deterministic(synthetic_docs: Path):
    """Same document produces same chunk IDs."""
    doc = parse_markdown(
        synthetic_docs / "01_SOP_Buka_Toko.md", "docs/01_SOP_Buka_Toko.md"
    )
    chunks1 = generate_chunks(doc, "v1")
    chunks2 = generate_chunks(doc, "v1")
    ids1 = [c.chunk_id for c in chunks1]
    ids2 = [c.chunk_id for c in chunks2]
    assert ids1 == ids2


def test_chunks_carry_source_metadata(synthetic_docs: Path):
    """Chunks include source file and heading path."""
    doc = parse_markdown(
        synthetic_docs / "02_FAQ_Pembayaran.md", "docs/02_FAQ_Pembayaran.md"
    )
    chunks = generate_chunks(doc, "v1")
    assert all(c.source_file == "02_FAQ_Pembayaran.md" for c in chunks)
    assert all(len(c.heading_path) > 0 for c in chunks)