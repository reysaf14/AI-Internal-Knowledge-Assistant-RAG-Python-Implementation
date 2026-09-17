"""Verify an eval-candidate CSV against the real index and the approved gate.

This is the Option A check: for every row whose referenced source exists in the
corpus, does the *amended* question now pass the approved support gate
(``min_matched_terms=2``, ``min_coverage=1.0``) on the real index?  And for every
row whose source is absent, does the gate correctly stay insufficient?

Read-only: no index write, no model call.  Prints counts and gate reasons only;
question text is echoed only because this is the dataset under review.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.query import normalize_query
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")
TARGET_SUPPORTED = 12
TARGET_UNSUPPORTED = 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    root = Path.cwd().resolve()
    load_operator_env(root)
    cfg = load_config(root)
    corpus = {p.stem for p in cfg.resolve_docs_path().glob("*.md")}
    store = IndexStore(cfg.resolve_index_path())
    gate = SupportGate()

    with (root / args.dataset).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        rows = list(reader)
    if headers != EXPECTED_HEADERS:
        raise SystemExit(f"headers mismatch: {headers}")

    supported_ok = 0
    unsupported_ok = 0
    supported_total = 0
    unsupported_total = 0
    for number, row in enumerate(rows, start=1):
        stem = (row.get("Dokumen_Sumber") or "").strip()
        question = (row.get("Pertanyaan") or "").strip()
        terms = normalize_query(question).terms
        candidates = store.search_terms(terms, limit=args.limit).chunks
        decision = gate.evaluate(terms, candidates)
        passed = decision.support_level.value == "sufficient"
        in_corpus = stem in corpus
        if in_corpus:
            supported_total += 1
            supported_ok += int(passed)
            state = "PASS" if passed else "GATE_FAIL"
        else:
            unsupported_total += 1
            unsupported_ok += int(not passed)
            state = "ABSTAINS_OK" if not passed else "LEAKS_SUPPORT"
        print(
            f"row={number:02d}|source_in_corpus={in_corpus}|terms={len(terms)}|"
            f"gate={decision.support_level.value}|reason={decision.reason or 'none'}|{state}"
        )

    shape_ok = supported_total == TARGET_SUPPORTED and unsupported_total == TARGET_UNSUPPORTED
    print(f"shape={supported_total} supported + {unsupported_total} unsupported "
          f"target_ok={shape_ok}")
    print(f"supported_gate_pass={supported_ok}/{supported_total}")
    print(f"unsupported_abstain_ok={unsupported_ok}/{unsupported_total}")
    verdict = "CANDIDATE_OK" if (
        shape_ok and supported_ok == supported_total and unsupported_ok == unsupported_total
    ) else "CANDIDATE_NOT_READY"
    print(f"verdict={verdict}")
    return 0 if verdict == "CANDIDATE_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
