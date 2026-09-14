"""Markdown heading-aware parser.

Reads Markdown files, preserves heading hierarchy, and splits into
sections while maintaining heading context for each chunk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ParsedSection:
    """A section of a Markdown document with heading hierarchy."""

    heading_path: str   # e.g. "# Company Profile > ## Location"
    heading_level: int  # deepest heading level in path
    content: str        # full text content of section


@dataclass(frozen=True)
class ParsedDocument:
    """Result of parsing one Markdown file."""

    filename: str
    relative_path: str
    sections: list[ParsedSection]


def _extract_headings(text: str) -> list[tuple[int, str, int]]:
    """Extract all headings with (position, text, level)."""
    result = []
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        heading_text = m.group(2).strip()
        result.append((m.start(), heading_text, level))
    return result


def parse_markdown(filepath: Path, relative_path: str) -> ParsedDocument:
    """Parse a Markdown file into heading-aware sections.

    Strategy:
    - Split on headings of level <= 3 as section boundaries
    - Each section carries its full heading path
    - Content between heading boundaries belongs to the section
    """
    text = filepath.read_text(encoding="utf-8")
    headings = _extract_headings(text)

    if not headings:
        return ParsedDocument(
            filename=filepath.name,
            relative_path=relative_path,
            sections=[
                ParsedSection(
                    heading_path=filepath.stem,
                    heading_level=0,
                    content=text.strip(),
                )
            ],
        )

    section_boundaries = [(pos, txt, lvl) for pos, txt, lvl in headings if lvl <= 3]

    if not section_boundaries:
        return ParsedDocument(
            filename=filepath.name,
            relative_path=relative_path,
            sections=[
                ParsedSection(
                    heading_path=filepath.stem,
                    heading_level=0,
                    content=text.strip(),
                )
            ],
        )

    sections: list[ParsedSection] = []
    heading_stack: list[str] = []
    heading_level_stack: list[int] = []

    for i, (pos, txt, lvl) in enumerate(section_boundaries):
        while heading_level_stack and heading_level_stack[-1] >= lvl:
            heading_stack.pop()
            heading_level_stack.pop()

        heading_stack.append(txt)
        heading_level_stack.append(lvl)

        line_end = text.find("\n", pos)
        heading_end = line_end + 1 if line_end != -1 else len(text)

        if i + 1 < len(section_boundaries):
            next_pos = section_boundaries[i + 1][0]
            content = text[heading_end:next_pos].strip()
        else:
            content = text[heading_end:].strip()

        if content:
            sections.append(
                ParsedSection(
                    heading_path=" > ".join(heading_stack),
                    heading_level=heading_level_stack[-1],
                    content=content,
                )
            )

    if not sections:
        sections.append(
            ParsedSection(
                heading_path=filepath.stem,
                heading_level=0,
                content=text.strip(),
            )
        )

    return ParsedDocument(
        filename=filepath.name,
        relative_path=relative_path,
        sections=sections,
    )