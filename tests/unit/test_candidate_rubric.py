"""Contract tests for the candidate eval rubric.

The rubric is the measuring instrument for every candidate-dataset claim.  Its
own docstring states two rules, and a rubric that breaks them silently is worse
than no rubric: an answer that merely echoes the question starts scoring as
correct, and the reported accuracy quietly becomes meaningless.

These tests assert the rules directly instead of trusting that reviewers will
notice:

1. every assertion term appears in the approved answer key for its row;
2. no term may also appear in the question it grades, except the one documented
   mandatory numeric anchor per row;
3. the exception list stays deliberate rather than growing one convenience term
   at a time.

Row 04 is the regression case: its term was ``"bonus"``, which is a word from
the question "Kasir Senior dapat bonus bulanan berapa?", so a model answer of
``Rp 500.000`` -- correct per the answer key -- scored as a failure.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "scripts"
DATASET = PROJECT_ROOT / "eval" / "QA_Dataset_12_3_candidate.csv"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from candidate_rubric import (
    RUBRIC,
    STRICT_ROWS,
    WEAK_ROWS,
    mandatory_numeric_anchors,
)


def _questions() -> list[str]:
    with DATASET.open(encoding="utf-8-sig", newline="") as handle:
        return [(row.get("Pertanyaan") or "") for row in csv.DictReader(handle)]


def _answer_keys() -> list[str]:
    with DATASET.open(encoding="utf-8-sig", newline="") as handle:
        return [(row.get("Jawaban_Benar") or "") for row in csv.DictReader(handle)]


def test_every_term_is_present_in_its_approved_answer_key():
    """A term that is not in the answer key is not an assertion, it is a guess."""
    keys = _answer_keys()
    offenders = [
        (number, term)
        for number, terms in RUBRIC.items()
        for term in terms
        if term.casefold() not in keys[number - 1].casefold()
    ]
    assert offenders == [], f"terms absent from approved answer key: {offenders}"


def test_no_term_is_lifted_from_its_own_question():
    """Only a mandatory numeric anchor may coincide with its question."""
    questions = _questions()
    anchors = set(mandatory_numeric_anchors())
    offenders = [
        (number, term)
        for number, terms in RUBRIC.items()
        for term in terms
        if term.casefold() in questions[number - 1].casefold() and term not in anchors
    ]
    assert offenders == [], (
        "terms duplicated from their own question let an answer that echoes the "
        f"question pass: {offenders}"
    )


def test_rows_are_never_graded_only_by_question_words():
    """Every graded row needs at least one term not found in its own question."""
    questions = _questions()
    weak = [
        number
        for number, terms in RUBRIC.items()
        if all(term.casefold() in questions[number - 1].casefold() for term in terms)
    ]
    assert weak == [], (
        f"rows whose every term is a question word grade nothing: {weak}"
    )


def test_mandatory_anchor_list_matches_the_rubric():
    """Keep the documented exception list honest and explicit."""
    anchors = set(mandatory_numeric_anchors())
    assert anchors <= {
        term for terms in RUBRIC.values() for term in terms
    }, "anchor list names terms that are not asserted anywhere"


@pytest.mark.parametrize("row", STRICT_ROWS)
def test_strict_rows_stay_strict(row: int):
    """Rows 5, 6 and 13 are real model-side failures and must stay visible.

    These rows are not required to hold a fixed number of terms -- an assertion
    term the approved key does not contain is a guess, not a rubric (see
    ``test_every_term_is_present_in_its_approved_answer_key``).  What must not
    happen is the row losing its grading, which would hide the failure.
    """
    assert row in RUBRIC, f"row {row} lost its assertion terms entirely"
    assert RUBRIC[row], f"row {row} was emptied, hiding a genuine failure"


def test_weak_rows_are_declared_not_accidental():
    """A row graded weakly must say why, so it is a decision, not an oversight."""
    for row, reason in WEAK_ROWS.items():
        assert row in RUBRIC, f"declared weak row {row} is not graded at all"
        assert reason.strip(), f"row {row} declares no reason"
        assert len(RUBRIC[row]) <= 1, (
            f"row {row} is declared weak but asserts {len(RUBRIC[row])} terms"
        )
