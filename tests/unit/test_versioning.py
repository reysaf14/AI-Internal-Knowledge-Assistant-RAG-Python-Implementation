"""Unit tests for corpus versioning."""
from rag_assistant.ingestion.versioning import compute_corpus_version, compute_file_hash


def test_version_deterministic():
    """Same input produces same version."""
    files = [("a.md", "content A"), ("b.md", "content B")]
    v1 = compute_corpus_version(files)
    v2 = compute_corpus_version(files)
    assert v1 == v2


def test_version_changes_on_content():
    """Different content produces different version."""
    v1 = compute_corpus_version([("a.md", "content1")])
    v2 = compute_corpus_version([("a.md", "content2")])
    assert v1 != v2


def test_version_changes_on_filename():
    """Different filename produces different version."""
    v1 = compute_corpus_version([("a.md", "content")])
    v2 = compute_corpus_version([("b.md", "content")])
    assert v1 != v2


def test_version_order_independent():
    """Order of files doesn't affect version."""
    v1 = compute_corpus_version([("a.md", "A"), ("b.md", "B")])
    v2 = compute_corpus_version([("b.md", "B"), ("a.md", "A")])
    assert v1 == v2


def test_file_hash_deterministic():
    """File hash is deterministic."""
    h1 = compute_file_hash("hello world")
    h2 = compute_file_hash("hello world")
    assert h1 == h2
    assert len(h1) == 8


def test_file_hash_differs():
    """Different content produces different hash."""
    h1 = compute_file_hash("hello")
    h2 = compute_file_hash("world")
    assert h1 != h2