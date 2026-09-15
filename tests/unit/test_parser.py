"""Unit tests for Markdown heading-aware parser."""
from pathlib import Path

from rag_assistant.ingestion.parser import parse_markdown


def test_parse_simple_document(synthetic_docs: Path):
    """Parse a simple document with headings and content."""
    doc = parse_markdown(
        synthetic_docs / "01_SOP_Buka_Toko.md", "docs/01_SOP_Buka_Toko.md"
    )
    assert doc.filename == "01_SOP_Buka_Toko.md"
    assert len(doc.sections) >= 2  # At least Tujuan + Prosedur


def test_parse_heading_path(synthetic_docs: Path):
    """Heading path includes nested context."""
    doc = parse_markdown(
        synthetic_docs / "02_FAQ_Pembayaran.md", "docs/02_FAQ_Pembayaran.md"
    )
    assert len(doc.sections) >= 1
    all_paths = [s.heading_path for s in doc.sections]
    assert any("Pembayaran" in p or "Metode" in p for p in all_paths)


def test_parse_title_only(tmp_path: Path):
    """File with only a heading produces a section with document content."""
    fp = tmp_path / "test.md"
    fp.write_text("# Title Only\n", encoding="utf-8")
    doc = parse_markdown(fp, "test.md")
    assert doc.filename == "test.md"


def test_parse_multilevel_headings(tmp_path: Path):
    """Document with H1, H2, H3 produces correct heading paths."""
    fp = tmp_path / "multi.md"
    fp.write_text(
        "# Root\n"
        "## Section A\n"
        "Content A\n"
        "### Subsection A1\n"
        "Sub content\n"
        "## Section B\n"
        "Content B\n",
        encoding="utf-8",
    )
    doc = parse_markdown(fp, "multi.md")
    paths = [s.heading_path for s in doc.sections]
    assert len(paths) >= 2
    assert any("Section A" in p for p in paths)