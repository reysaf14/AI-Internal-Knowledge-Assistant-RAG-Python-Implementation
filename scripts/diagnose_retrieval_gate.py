"""Read-only diagnostic for the support-gate recall boundary.

Answers one question with evidence instead of opinion: *for the approved CSV
questions, how many query terms can a real chunk actually match?*  It prints
only counts and the gate's own technical terms-of-art -- never question text,
answer text, or chunk bodies.

No index is written; no model is called.  Safe to run at any time.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.query import matched_query_terms, normalize_query
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")


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
    info = store.get_index_info()
    if info is None:
        raise RuntimeError("active index is unavailable or invalid")

    gate = SupportGate()
    print(f"index_files={info.file_count}")
    print(f"gate_min_matched_terms={gate.min_matched_terms}")
    print(f"gate_min_coverage={gate.min_coverage}")
    print(f"gate_min_single_term_length={gate.min_single_term_length}")

    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    print(f"rows={len(rows)}")
    # term-count -> how many rows, so the coverage arithmetic is visible.
    histogram: dict[int, int] = {}
    supported_rows = 0
    for row_number, row in enumerate(rows, start=1):
        stem = (row.get("Dokumen_Sumber") or "").strip()
        if stem not in corpus_stems:
            continue
        supported_rows += 1
        normalized = normalize_query((row.get("Pertanyaan") or "").strip())
        terms = normalized.terms
        required = gate._required_matches(terms)
        candidates = store.search_terms(terms, limit=args.limit)
        best_matched = 0
        for chunk in candidates.chunks:
            matched = matched_query_terms(terms, f"{chunk.heading_path} {chunk.text}")
            best_matched = max(best_matched, len(matched))
        histogram[len(terms)] = histogram.get(len(terms), 0) + 1
        decision = gate.evaluate(terms, candidates.chunks)
        verdict = "SUFFICIENT" if decision.support_level.value == "sufficient" else "INSUFFICIENT"
        print(
            f"row={row_number:02d}|terms={len(terms)}|required={required}|"
            f"best_matched={best_matched}|candidates={len(candidates.chunks)}|"
            f"gate={verdict}|reason={decision.reason or 'none'}"
        )

    print(f"corpus_compatible_rows={supported_rows}")
    print(f"unreachable_rows={sum(1 for r in rows if (r.get('Dokumen_Sumber') or '').strip() not in corpus_stems)}")
    print("term_count_histogram=" + ",".join(f"{k}:{v}" for k, v in sorted(histogram.items())))
    print(
        "coverage_1.0_requires_all_terms_in_one_chunk=true "
        "(i.e. required==terms for every multi-term row)"
    )
    # What a coverage-based gate would need instead, shown as arithmetic only.
    for target in (0.6, 0.7, 0.8):
        reqs = sorted({max(2, math.ceil(t * target)) for t in histogram})
        print(f"hypothetical_coverage_{target}_required_matches={reqs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
