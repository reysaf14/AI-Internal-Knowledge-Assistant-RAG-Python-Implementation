"""Assertion terms and scoring rules for the approved English 12+3 M5 set."""
from __future__ import annotations

from typing import NamedTuple

# Row number -> terms that must appear in the answer body.
# Each term comes from the English answer key and is absent from its question.
RUBRIC: dict[int, tuple[str, ...]] = {
    1: ("21",),
    2: ("12",),
    4: ("500,000",),
    5: ("3",),
    6: ("cash", "QRIS", "debit"),
    8: ("200,000",),
    9: ("rejection", "photo"),
    10: ("no",),
    11: ("75,000",),
    12: ("300,000",),
    13: ("discount", "discard"),
    14: ("annual leave", "deducted"),
}

# These rows remain strict so the test cannot hide incomplete or vague answers.
STRICT_ROWS: tuple[int, ...] = (5, 6, 13)

# Row 10 has one intentionally minimal assertion: the answer must negate the
# existence of a current member program, without grading speculative launch detail.
WEAK_ROWS: dict[int, str] = {
    10: "only the approved answer key's current-state negation is asserted",
}

# The English questions do not repeat the answer figures, so no numeric anchor
# exception is required in this revision.
MANDATORY_NUMERIC_ANCHORS: dict[int, str] = {}


def mandatory_numeric_anchors() -> tuple[str, ...]:
    """Return the explicitly approved numeric-anchor exceptions."""
    return tuple(MANDATORY_NUMERIC_ANCHORS.values())


class OutcomeRow(NamedTuple):
    """One scored row, family flag plus the four per-row verdicts."""

    case_id: str
    expected_supported: bool
    content_ok: bool
    source_ok: bool
    abstention_ok: bool
    latency_ok: bool
    response_count: int


class OutcomeSummary(NamedTuple):
    """Aggregate scored over rows, each metric scoped to its own family."""

    total: int
    expected_supported: int
    expected_unsupported: int
    content_passed: int
    supported_content_passed: int
    source_passed: int
    abstention_passed: int
    latency_passed: int
    responses_sent: int
    duplicates: int


def summarize_outcomes(rows: tuple[OutcomeRow, ...]) -> OutcomeSummary:
    """Aggregate content, source, abstention, latency, and delivery outcomes."""
    supported = tuple(row for row in rows if row.expected_supported)
    unsupported = tuple(row for row in rows if not row.expected_supported)
    return OutcomeSummary(
        total=len(rows),
        expected_supported=len(supported),
        expected_unsupported=len(unsupported),
        content_passed=sum(1 for row in rows if row.content_ok),
        supported_content_passed=sum(1 for row in supported if row.content_ok),
        source_passed=sum(1 for row in supported if row.source_ok),
        abstention_passed=sum(1 for row in unsupported if row.abstention_ok),
        latency_passed=sum(1 for row in rows if row.latency_ok),
        responses_sent=sum(1 for row in rows if row.response_count >= 1),
        duplicates=sum(max(row.response_count - 1, 0) for row in rows),
    )


def outcomes_meet_targets(summary: OutcomeSummary) -> bool:
    """Check the PRD's 12+3 content, source, abstention, latency, and delivery gates."""
    return (
        summary.total == 15
        and summary.expected_supported == 12
        and summary.expected_unsupported == 3
        and summary.content_passed >= summary.expected_supported
        and summary.source_passed == summary.expected_supported
        and summary.abstention_passed == summary.expected_unsupported
        and summary.latency_passed == summary.total
        and summary.responses_sent == summary.total
        and summary.duplicates == 0
    )
