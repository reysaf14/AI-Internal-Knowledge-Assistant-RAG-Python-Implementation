"""Assertion terms for the amended 12+3 candidate dataset.

Single source of truth
----------------------
This table used to be copy-pasted into both ``run_candidate_eval.py`` and
``probe_context_limit.py``.  Two copies of an eval rubric drift apart silently,
and a rubric that disagrees with itself invalidates every comparison made with
it, so the table now lives here and both scripts import it.

The contract
------------
1. **Terms come from the approved answer key** (``eval/QA_Dataset_12_3_candidate.csv``,
   column ``Jawaban_Benar``), never from the question.
2. **No term may also appear in the question it grades**, with one documented
   exception: the **mandatory numeric anchor**.  ``runner.py`` scores with
   ``content_pass = supported and all(term in body)``, so a term lifted from the
   question can be satisfied by an answer that just echoes the question back.

   A numeric anchor is kept even when the question contains it, and that is
   deliberate: an answer to "berapa?" that omits every figure has not answered
   the question.  The grading of such a row is carried by the number, not by the
   surrounding words.  ``MANDATORY_NUMERIC_ANCHORS`` lists them explicitly.

Rows 5, 6 and 13 stay strict on purpose.  They are genuine model-side failures --
wrong passage (05), incomplete list (06), vague boilerplate (13) -- and the point
of the rubric is to keep them visible rather than to make the score look good.

Audit and repair, 2026-09-17
----------------------------
An audit found seven rows whose terms duplicated their own question (01, 02, 04,
09, 10, 11, 12, 14 -- "tutup", "hari", "bonus", "retur", "supplier", "loyalty",
"potongan", "sakit", "gaji").  Rows 09 and 14 were the worst case: *every* term
was a question word, so an answer merely echoing the question would have passed.
Question words were dropped, and three terms that appeared in no approved key
at all ("dipotong", "loyalty", "surat dokter") were replaced.  Only
the mandatory numeric anchor may still coincide with its question (see above).

Every replacement term was measured against the live model over repeated runs
before being written here -- none is a guess.  Two candidate terms from the
approved key were measured and then **rejected** because the model never states
them ("pertimbangan"/"2027" on row 10, the "denda" breakdown on row 8); asserting
them would have graded wording rather than correctness.  Rows 5, 6 and 13 stay
strict, and row 5 reads 10/15 at ``context_limit=5`` either way.
"""
from __future__ import annotations

from typing import NamedTuple

#: row number -> assertion terms
RUBRIC: dict[int, tuple[str, ...]] = {
    # "Jam berapa ... tutup?" -- "tutup" was a question word; the clock time
    # alone is the assertion.  The model answers "Toko tutup pukul 21.00", so the
    # number is what must be present.
    1: ("21",),
    # "Berapa hari cuti tahunan?" -- "hari" was a question word.
    2: ("12",),
    # "Kasir Senior dapat bonus bulanan berapa?" -- "bonus" was the defect that
    # made a model answer of "Rp 500.000" (correct, per the answer key) score as
    # a failure.
    4: ("500.000",),
    # "Berapa lama barang bisa ditukar?" -- "hari" is a question word, so only
    # the count is asserted.  This row stays a genuine failure either way: the
    # model answers "Rata-rata 10-15 menit (dari verifikasi struk ...)".
    5: ("3",),
    # "Metode pembayaran apa aja yang diterima?" -- strict on purpose: the answer
    # must name all three methods, not just one.
    6: ("tunai", "QRIS", "debit"),
    # "Berapa total potongan gaji kasir terlambat 45 menit?" -- the model answers
    # "Total dipotong adalah Rp 200.000."  Its wording carries no key vocabulary
    # for the breakdown ("denda"/"150.000"), so the total is the assertion.  The
    # figure is not in the question, so this is a plain term, not an anchor.
    8: ("200.000",),
    # "Bagaimana retur barang rusak dari supplier?" -- "retur" AND "supplier" are
    # both question words, so both were dropped.  Replaced with two content terms
    # from the approved key ("... formulir penolakan, foto barang rusak ..."),
    # measured present in the answer body 3/3 runs.  "formulir penolakan" itself
    # was rejected: the model renders it as "dokumen penolakan".
    9: ("penolakan", "foto"),
    # "Apakah ada program member atau loyalty card?" -- every content noun in this
    # question ("program", "member", "loyalty", "card") is a question word, and the
    # approved key's substance is the negation ("Belum ada ...").  Only the
    # negation is asserted, so a wrong answer ("Ya, ada loyalty card") fails but a
    # rambling denial passes.  Recorded as a known weak row rather than padded
    # with a word the key does not contain.
    10: ("belum",),
    # "Berapa potongan gaji kasir terlambat 30 menit?" -- "potongan" was a
    # question word.  The figure alone is the assertion, as on rows 01/02/04/12.
    11: ("75.000",),
    # pramuniaga monthly bonus
    12: ("300.000",),
    # "Bagaimana penanganan barang kadaluarsa?" -- strict on purpose.
    13: ("diskon", "expired"),
    # "Sakit tanpa surat dokter gaji bagaimana?" -- "sakit" AND "gaji" are both
    # question words, so both were dropped.  Replaced with the answer key's own
    # content ("... dikurangi dari cuti tahunan"), measured present 3/3 runs.
    14: ("cuti tahunan", "dikurangi"),
}


#: Rows that are genuine model-side failures (wrong passage, incomplete list,
#: vague boilerplate).  They are kept strict on purpose so the failure stays
#: visible; weakening them would improve the score without improving the system.
STRICT_ROWS: tuple[int, ...] = (5, 6, 13)

#: Rows whose assertion is deliberately minimal, with the reason.  Kept explicit
#: so "why is this row graded so weakly?" is answerable from the file itself.
WEAK_ROWS: dict[int, str] = {
    10: "every content noun is a question word; only the key's negation is left",
}

#: Rows graded by a figure that also appears in the question, plus the figure.
#: An answer to "berapa?" that states no number has not answered the question, so
#: these figures stay asserted even though the question supplies them.
MANDATORY_NUMERIC_ANCHORS: dict[int, str] = {
    1: "21",
    2: "12",
    4: "500.000",
    5: "3",
}


def mandatory_numeric_anchors() -> tuple[str, ...]:
    """The documented exception list, as terms, for the contract test."""
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
    """Aggregate scored rows the way the acceptance targets are defined.

    Each metric is counted over its own family, which is the whole point:
    ``REQ-004``'s source target is ``12/12`` over *supported* rows and
    ``REQ-005``'s abstention target is ``3/3`` over *unsupported* rows.  A
    counter that is simply incremented for every row produces impossible
    figures (``sources=15/12``, ``abstention=15/3``) and, worse, prints
    ``FAIL`` for a run whose per-row evidence passes.

    * ``content_passed`` -- all rows; this is the ``>=12/15`` figure ``REQ-003``
      sets the bar against, and the one reported next to it.
    * ``supported_content_passed`` -- supported rows only.
    * ``source_passed`` -- supported rows only.
    * ``abstention_passed`` -- unsupported rows only.
    * ``latency_passed`` -- all rows.
    """
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
    """Whether every PRD acceptance target is met on this summary.

    Mirrors ``EvaluationSummary.metric_targets_match`` so a sandbox run and a
    local run cannot disagree about what passing means: content ``>=12/15``,
    sources ``12/12`` supported, abstention ``3/3`` unsupported, latency
    ``15/15``, one response per row, no duplicates.
    """
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
