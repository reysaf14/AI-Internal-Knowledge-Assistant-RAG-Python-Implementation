"""Contract tests for the shared eval aggregation.

The bug these guard against was silent and inverted: a run whose per-row
evidence showed every target met printed ``sources=15/12``, ``abstention=15/3``
and ``supported_content=-3/12``, then declared ``FAIL``.  Each counter had been
incremented for *every* row instead of only the rows in its own family, so the
aggregate contradicted the evidence printed directly above it.

Aggregation lives in one place (``scripts/candidate_rubric.py``) precisely
because two copies of a scoring rule drift apart, and a rubric that disagrees
with itself invalidates every comparison made with it.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from candidate_rubric import (
    OutcomeRow,
    outcomes_meet_targets,
    summarize_outcomes,
)


def _row(
    index: int,
    *,
    supported: bool,
    content_ok: bool = True,
    source_ok: bool = True,
    abstention_ok: bool = True,
    latency_ok: bool = True,
    responses: int = 1,
) -> OutcomeRow:
    return OutcomeRow(
        case_id=f"cand-{index:02d}",
        expected_supported=supported,
        content_ok=content_ok,
        source_ok=source_ok,
        abstention_ok=abstention_ok,
        latency_ok=latency_ok,
        response_count=responses,
    )


def _passing_run() -> tuple[OutcomeRow, ...]:
    """12 supported and 3 unsupported rows, all targets met."""
    return tuple(
        [_row(index, supported=True) for index in range(1, 13)]
        + [_row(index, supported=False) for index in range(13, 16)]
    )


def test_each_metric_is_scoped_to_its_own_family():
    """Source and abstention counts are per-family, never per-row.

    With all 15 rows passing, a source counter incremented for every row would
    read ``15`` against a denominator of ``12``, and abstention would read
    ``15`` against ``3`` -- both impossible.
    """
    summary = summarize_outcomes(_passing_run())

    assert summary.total == 15
    assert summary.expected_supported == 12
    assert summary.expected_unsupported == 3
    assert summary.content_passed == 15
    # The two counts that were wrong: both are bounded by their own family.
    assert summary.source_passed == 12
    assert summary.abstention_passed == 3
    # And no counter can exceed its denominator.
    assert summary.source_passed <= summary.expected_supported
    assert summary.abstention_passed <= summary.expected_unsupported
    assert summary.latency_passed == 15
    assert summary.responses_sent == 15
    assert summary.duplicates == 0


def test_supported_content_excludes_unsupported_rows():
    """``supported_content`` counts supported rows only, so it cannot go negative."""
    rows = list(_passing_run())
    # An unsupported row that misses content must not subtract from a
    # supported-only metric.
    rows[12] = _row(13, supported=False, content_ok=False)

    summary = summarize_outcomes(tuple(rows))

    assert summary.content_passed == 14
    assert summary.supported_content_passed == 12
    assert summary.supported_content_passed >= 0


def test_targets_met_for_a_twelve_of_fifteen_run():
    """``REQ-003``'s bar is "at least 12/15", so 12/15 with the rest met passes."""
    assert outcomes_meet_targets(summarize_outcomes(_passing_run()))


def test_targets_not_met_below_the_bar_or_with_a_duplicate():
    """A genuine miss still fails, so the gate has not simply been loosened."""
    below = list(_passing_run())
    below[0] = _row(1, supported=True, content_ok=False)
    below[1] = _row(2, supported=True, content_ok=False)
    below[2] = _row(3, supported=True, content_ok=False)
    below[3] = _row(4, supported=True, content_ok=False)  # content now 11/15

    assert not outcomes_meet_targets(summarize_outcomes(tuple(below)))

    duplicated = list(_passing_run())
    duplicated[0] = _row(1, supported=True, responses=2)

    assert not outcomes_meet_targets(summarize_outcomes(tuple(duplicated)))


def test_targets_not_met_when_a_supported_row_cites_no_source():
    """A missing source on one supported row keeps the run below ``12/12``."""
    rows = list(_passing_run())
    rows[5] = _row(6, supported=True, source_ok=False)

    summary = summarize_outcomes(tuple(rows))

    assert summary.source_passed == 11
    assert not outcomes_meet_targets(summary)
