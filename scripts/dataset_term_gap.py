"""Evidence for the Option A dataset amendment: per-row term co-occurrence.

For each row whose referenced source exists in the corpus, show which query
terms a single chunk of that source can actually match.  A rewrite is only
valid if every remaining content term fits inside one chunk (the gate requires
100% coverage).

Run output is working evidence, not a persisted artifact.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.query import matched_query_terms, normalize_query
from rag_assistant.retrieval.support_gate import SupportGate
from rag_assistant.storage.index_store import IndexStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("eval/QA_Dataset_15_Pasangan.csv"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    root = Path.cwd().resolve()
    load_operator_env(root)
    cfg = load_config(root)
    corpus = {p.stem for p in cfg.resolve_docs_path().glob("*.md")}
    store = IndexStore(cfg.resolve_index_path())
    gate = SupportGate()

    with (root / args.dataset).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    for number, row in enumerate(rows, start=1):
        stem = (row.get("Dokumen_Sumber") or "").strip()
        if stem not in corpus:
            continue
        terms = normalize_query((row.get("Pertanyaan") or "").strip()).terms
        candidates = store.search_terms(terms, limit=args.limit).chunks
        decision = gate.evaluate(terms, candidates)
        if decision.support_level.value == "sufficient":
            print(f"row={number:02d} PASS terms={list(terms)}")
            continue

        # Best single chunk by matched-term count.
        best_matched: tuple[str, ...] = ()
        best_heading = ""
        best_chunk_id = ""
        for chunk in candidates:
            matched = matched_query_terms(terms, f"{chunk.heading_path} {chunk.text}")
            if len(matched) > len(best_matched):
                best_matched = matched
                best_heading = chunk.heading_path
                best_chunk_id = chunk.chunk_id
        missing = tuple(t for t in terms if t not in best_matched)
        print(f"row={number:02d} FAIL source={stem}")
        print(f"  terms={list(terms)}")
        print(f"  cooccurring={list(best_matched)}")
        print(f"  missing_from_single_chunk={list(missing)}")
        print(f"  best_chunk_id={best_chunk_id} heading={best_heading!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
