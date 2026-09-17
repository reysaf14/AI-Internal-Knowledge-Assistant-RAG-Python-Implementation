"""Read-only diagnostic: where does the *expected* source chunk rank?

``diagnose_retrieval_gate.py`` proves the gate's coverage arithmetic.  It does
not answer the question that actually explains the remaining content failures:
the gate can pass, the expected chunk can exist, and the answer can still be
wrong because the expected chunk is **not** in the context that reaches the
model.

This script measures exactly that, in three positions, per row:

* ``gate_rank``   -- position within the gate's ranked match list (0-based);
* ``ctx_rank``    -- position within the ``context_limit`` slice the model sees,
                     or ``-1`` when the expected chunk is dropped entirely;
* ``ctx_sources`` -- how many *distinct* sources occupy that slice.

Only counts, ranks, source stems that are already part of the approved dataset
contract, and gate terms-of-art are printed.  No question text, no answer text,
no chunk body.

Nothing is written; no model is called.  Safe to run at any time.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.query import normalize_query
from rag_assistant.retrieval.service import RetrievalPolicy
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("eval/QA_Dataset_12_3_candidate.csv")
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()
    load_operator_env(root)
    cfg = load_config(root)

    dataset_path = (root / args.dataset).resolve()
    corpus_stems = {path.stem for path in cfg.resolve_docs_path().glob("*.md")}

    store = IndexStore(cfg.resolve_index_path())
    info = store.get_index_info()
    if info is None:
        raise RuntimeError("active index is unavailable or invalid")

    policy = RetrievalPolicy()
    gate = SupportGate(
        min_matched_terms=policy.min_matched_terms,
        min_coverage=policy.min_coverage,
        min_single_term_length=policy.min_single_term_length,
    )
    print(f"candidate_limit={policy.candidate_limit}")
    print(f"context_limit={policy.context_limit}")

    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        if tuple(csv.DictReader(handle).fieldnames or ()) != EXPECTED_HEADERS:
            raise ValueError("dataset headers do not match the approved contract")

    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    dropped = 0
    mismatched = 0
    for row_number, row in enumerate(rows, start=1):
        stem = (row.get("Dokumen_Sumber") or "").strip()
        if stem not in corpus_stems:
            print(f"row={row_number:02d}|skipped=out_of_corpus")
            continue

        expected = f"{stem}.md"
        terms = normalize_query((row.get("Pertanyaan") or "").strip()).terms
        candidates = store.search_terms(terms, limit=policy.candidate_limit)
        decision = gate.evaluate(terms, candidates.chunks)
        if decision.support_level.value != "sufficient":
            print(
                f"row={row_number:02d}|gate=INSUFFICIENT"
                f"|reason={decision.reason or 'none'}"
            )
            continue

        gate_rank = next(
            (
                index
                for index, match in enumerate(decision.matches)
                if match.chunk.source_file == expected
            ),
            -1,
        )
        context = decision.chunks[: policy.context_limit]
        ctx_rank = next(
            (
                index
                for index, chunk in enumerate(context)
                if chunk.source_file == expected
            ),
            -1,
        )
        ctx_sources = len({chunk.source_file for chunk in context})

        if gate_rank >= 0 and ctx_rank < 0:
            dropped += 1
        if ctx_rank != 0:
            mismatched += 1
        print(
            f"row={row_number:02d}|gate_passed=true|gate_rank={gate_rank}"
            f"|ctx_rank={ctx_rank}|ctx_sources={ctx_sources}"
            f"|expected_at_top={'yes' if ctx_rank == 0 else 'no'}"
        )

    print(f"dropped_by_context_limit={dropped}")
    print(f"not_ranked_first={mismatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
