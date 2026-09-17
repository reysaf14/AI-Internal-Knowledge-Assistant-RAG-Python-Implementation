"""Read-only precision/recall sweep for the M2 support-gate policy.

The approved CSV is the only labelled data available, so it is used to answer a
narrow, honest question: *if the gate were loosened, how much supported recall is
gained and how much out-of-corpus precision is lost?*

This script **changes nothing**.  It re-instantiates :class:`SupportGate` with
candidate parameters and reports pass/fail counts.  The M2 policy itself is an
approved artifact, so any actual parameter change requires Human approval; this
output exists so that decision can be made on evidence rather than opinion.

Output is aggregate counts plus the gate's own technical reasons.  Question
text, answer text, and chunk bodies are never printed.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.query import normalize_query
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore

CANDIDATE_COVERAGE = (1.0, 0.8, 0.7, 0.6, 0.5, 0.4)
CANDIDATE_MIN_MATCHED = (2, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("eval/QA_Dataset_15_Pasangan.csv"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    project_root = Path.cwd().resolve()
    load_operator_env(project_root)
    cfg = load_config(project_root)

    dataset_path = (project_root / args.dataset).resolve()
    corpus_stems = {path.stem for path in cfg.resolve_docs_path().glob("*.md")}
    store = IndexStore(cfg.resolve_index_path())

    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    cases: list[tuple[tuple[str, ...], bool, list]] = []
    for row in rows:
        stem = (row.get("Dokumen_Sumber") or "").strip()
        supported = stem in corpus_stems
        terms = normalize_query((row.get("Pertanyaan") or "").strip()).terms
        candidates = store.search_terms(terms, limit=args.limit).chunks
        cases.append((terms, supported, list(candidates)))

    supported_total = sum(1 for _t, s, _c in cases if s)
    unsupported_total = len(cases) - supported_total
    print(f"rows={len(cases)}")
    print(f"supported_rows={supported_total}")
    print(f"out_of_corpus_rows={unsupported_total}")
    print("note=approved policy is min_coverage=1.0/min_matched_terms=2; rows below are hypothetical")
    print("coverage|min_matched|supported_pass|supported_recall|out_of_corpus_false_positive|precision_risk")

    for coverage in CANDIDATE_COVERAGE:
        for min_matched in CANDIDATE_MIN_MATCHED:
            gate = SupportGate(min_matched_terms=min_matched, min_coverage=coverage)
            supported_pass = 0
            false_positive = 0
            for terms, supported, candidates in cases:
                decision = gate.evaluate(terms, candidates)
                passed = decision.support_level.value == "sufficient"
                if supported and passed:
                    supported_pass += 1
                elif not supported and passed:
                    false_positive += 1
            recall = supported_pass / supported_total if supported_total else 0.0
            print(
                f"{coverage}|{min_matched}|{supported_pass}/{supported_total}|"
                f"{recall:.2f}|{false_positive}/{unsupported_total}|"
                f"{'none' if false_positive == 0 else 'out_of_corpus_now_answered'}"
            )

    # Which out-of-corpus rows become answerable as the gate loosens: shown as
    # row numbers only, so the dataset content never appears in evidence.
    loosened = SupportGate(min_matched_terms=2, min_coverage=0.5)
    enabled: list[int] = []
    for row_number, (terms, supported, candidates) in enumerate(cases, start=1):
        if supported:
            continue
        if loosened.evaluate(terms, candidates).support_level.value == "sufficient":
            enabled.append(row_number)
    print("out_of_corpus_rows_enabled_at_coverage_0.5=" + (",".join(map(str, enabled)) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
