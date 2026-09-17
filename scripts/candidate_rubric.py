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
   surrounding words.

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
before being written here -- none is a guess.  Rows 5, 6 and 13 were left strict.
"""
from __future__ import annotations

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
    # "Berapa lama barang bisa ditukar?" -- strict on purpose (see module doc).
    5: ("3", "hari"),
    # "Metode pembayaran apa aja yang diterima?" -- strict on purpose: the answer
    # must name all three methods, not just one.
    6: ("tunai", "QRIS", "debit"),
    # late cashier 45 min = Rp 200.000 (150.000 potongan + 50.000 denda).
    # "dipotong" was asserted but does not appear in the approved key at all;
    # "denda" does, and is absent from the question.
    8: ("200.000", "denda"),
    # "Bagaimana retur barang rusak dari supplier?" -- "retur" AND "supplier" are
    # both question words, so both were dropped.  Replaced with two content terms
    # from the approved key ("... formulir penolakan, foto barang rusak ..."),
    # measured present in the answer body 3/3 runs.  "formulir penolakan" itself
    # was rejected: the model renders it as "dokumen penolakan".
    9: ("penolakan", "foto"),
    # "Apakah ada program member atau loyalty card?" -- "loyalty" was both a
    # question word and absent from the key.  The key's own content is
    # "Belum ada (sedang dalam pertimbangan ...)".
    10: ("belum", "pertimbangan"),
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


def mandatory_numeric_anchors() -> tuple[str, ...]:
    """Terms kept despite appearing in their own question (one per graded row).

    Exposed so a test can assert the exception list stays deliberate instead of
    growing by accident.
    """
    return ("21", "12", "500.000", "3", "75.000", "300.000", "200.000")
