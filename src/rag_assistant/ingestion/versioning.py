"""Corpus versioning: deterministic hash from file list + content.

corpus_version is a SHA256 of sorted (filename, content_hash) pairs.
Same files + same content = same version; any change = different version.
"""
from __future__ import annotations

import hashlib


def compute_corpus_version(files: list[tuple[str, str]]) -> str:
    """Compute deterministic corpus version from (filename, content) pairs.

    Args:
        files: list of (filename, content_text) tuples, sorted by filename.

    Returns:
        Short SHA256 hash (16 hex chars) representing this corpus version.
    """
    sorted_files = sorted(files, key=lambda x: x[0])
    combined = "\n".join(f"{name}||{content}" for name, content in sorted_files)
    full_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return full_hash[:16]


def compute_file_hash(content: str) -> str:
    """SHA256 hash of file content (8 hex chars)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]