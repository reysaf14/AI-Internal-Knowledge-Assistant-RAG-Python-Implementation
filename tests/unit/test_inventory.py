"""Unit tests for ingestion inventory module.

Covers AC-001 (valid scan), AC-002 (invalid corpus).
Using a 5-file synthetic corpus for speed; real corpus is 26 files.
"""
from pathlib import Path

from rag_assistant.ingestion.inventory import (
    scan_corpus,
)


def test_scan_valid_corpus(synthetic_docs: Path):
    """AC-001: scan a valid corpus returns all items and is_valid=True."""
    result = scan_corpus(synthetic_docs, expected_file_count=5)
    assert result.is_valid, f"Expected valid, got errors: {result.errors}"
    assert len(result.items) == 5
    prefixes = [item.prefix for item in result.items]
    assert prefixes == [0, 1, 2, 3, 4]


def test_scan_empty_directory(empty_docs: Path):
    """AC-002: empty directory fails with count mismatch."""
    result = scan_corpus(empty_docs, expected_file_count=5)
    assert not result.is_valid
    assert any("Expected 5" in e for e in result.errors)


def test_scan_wrong_prefix(invalid_docs: Path):
    """AC-002: files with prefix outside 00-25 range fail."""
    result = scan_corpus(invalid_docs, expected_file_count=2)
    assert not result.is_valid
    assert any("outside valid range" in e for e in result.errors)


def test_scan_nonexistent_dir(tmp_path: Path):
    """AC-002: non-existent directory fails."""
    result = scan_corpus(tmp_path / "nonexistent")
    assert not result.is_valid
    assert any("not found" in e.lower() for e in result.errors)


def test_scan_sorting(synthetic_docs: Path):
    """Items are sorted by prefix ascending."""
    result = scan_corpus(synthetic_docs, expected_file_count=5)
    assert result.is_valid
    prefixes = [item.prefix for item in result.items]
    assert prefixes == sorted(prefixes)