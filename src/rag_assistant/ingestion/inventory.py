"""Corpus inventory: scan docs/ for official Markdown files (00-25).

Validates filename pattern, range, and readability.
Baseline: exactly 26 files matching XX_*.md where XX is 00..25.
Test profile may lower the expected count for synthetic fixtures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FILENAME_PATTERN = re.compile(r"^(\d{2})_(.+)\.md$")
_VALID_PREFIXES = set(range(26))  # 00..25 inclusive
DEFAULT_EXPECTED_FILE_COUNT = 26


@dataclass(frozen=True)
class InventoryItem:
    """One valid corpus file."""

    prefix: int
    filename: str
    relative_path: str


@dataclass(frozen=True)
class InventoryResult:
    """Result of corpus inventory scan."""

    items: list[InventoryItem]
    is_valid: bool
    errors: list[str]


def scan_corpus(docs_dir: Path, expected_file_count: int = DEFAULT_EXPECTED_FILE_COUNT) -> InventoryResult:
    """Scan docs_dir for valid corpus files.

    Fails if any of:
      - fewer/more than expected count of files
      - any filename outside XX_*.md pattern
      - any prefix outside 00..25
      - any file unreadable
    """
    errors: list[str] = []
    items: list[InventoryItem] = []

    if not docs_dir.is_dir():
        return InventoryResult(
            items=[], is_valid=False, errors=[f"Docs directory not found: {docs_dir}"]
        )

    md_files = sorted(docs_dir.glob("*.md"))

    if len(md_files) != expected_file_count:
        errors.append(f"Expected {expected_file_count} files, found {len(md_files)}")
        return InventoryResult(items=[], is_valid=False, errors=errors)

    seen_prefixes: set[int] = set()

    for fp in md_files:
        m = _FILENAME_PATTERN.match(fp.name)
        if not m:
            errors.append(f"Filename does not match pattern XX_name.md: {fp.name}")
            continue

        prefix = int(m.group(1))

        if prefix not in _VALID_PREFIXES:
            errors.append(f"Prefix {prefix:02d} is outside valid range 00-25: {fp.name}")
            continue

        if prefix in seen_prefixes:
            errors.append(f"Duplicate prefix {prefix:02d}: {fp.name}")
            continue

        try:
            fp.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - any read failure marks file invalid
            errors.append(f"Cannot read {fp.name}: {exc}")
            continue

        seen_prefixes.add(prefix)
        items.append(
            InventoryItem(
                prefix=prefix,
                filename=fp.name,
                relative_path=str(fp.relative_to(docs_dir.parent)),
            )
        )

    items.sort(key=lambda x: x.prefix)
    return InventoryResult(items=items, is_valid=len(errors) == 0, errors=errors)