"""Chunk generation from parsed Markdown sections.

Each parsed section becomes one chunk carrying source metadata.
"""
from __future__ import annotations

import hashlib

from rag_assistant.domain.types import ChunkData
from rag_assistant.ingestion.parser import ParsedDocument


def _chunk_id(source_file: str, heading_path: str, text: str) -> str:
    """Deterministic chunk ID from source + heading + content hash."""
    h = hashlib.sha256(
        f"{source_file}||{heading_path}||{text}".encode()
    ).hexdigest()[:16]
    return f"{source_file}::{h}"


def generate_chunks(doc: ParsedDocument, corpus_version: str) -> list[ChunkData]:
    """Convert parsed document sections into ChunkData objects.

    Each non-empty section produces exactly one chunk.
    """
    chunks: list[ChunkData] = []

    for section in doc.sections:
        if not section.content.strip():
            continue

        chunk = ChunkData(
            chunk_id=_chunk_id(doc.filename, section.heading_path, section.content),
            text=section.content,
            source_file=doc.filename,
            heading_path=section.heading_path,
            corpus_version=corpus_version,
        )
        chunks.append(chunk)

    return chunks