"""Read-only: which required keyword does the model's answer miss?

Why this exists
---------------
``probe_context_limit.py`` showed two rows failing at *every* ``context_limit``
including ``1``.  ``diagnose_context_assembly.py`` then showed the expected
chunk sitting at ``gate_rank=0`` / ``ctx_rank=0`` for both -- so the retrieval
and gate layers are provably fine.  That leaves the model's own wording as the
only remaining explanation, and this script pins it down without guessing.

It answers one row through the real M2/M3 path per limit, then reports *which
rubric keywords are absent* from the answer.  That is the whole diagnosis:

* a missing numeric keyword (``"3"``) usually means the model wrote the number
  out in words -- a small-model habit, not a retrieval fault;
* a missing content keyword (``"debit"``) means the model dropped part of a
  list it was given.

Neither can be fixed by changing ``context_limit``, which is exactly why this
measurement matters: it separates "the pipeline did not deliver the fact" from
"the model did not repeat the fact".

Only presence/absence of keywords is printed -- never question text, answer
text, or chunk bodies.  Keyword lists are imported from ``probe_context_limit``
so the two scripts can never drift apart.  Read-only: no index or artefact is
written.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from probe_context_limit import CANDIDATE_RUBRIC, prewarm

from rag_assistant.answering.service import build_answer_service
from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.service import RetrievalPolicy, Retriever
from rag_assistant.storage.index_store import IndexStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path("eval/QA_Dataset_12_3_candidate.csv")

# Rubric keywords are matched the same way the eval runner matches them, so the
# verdict here always agrees with the score in the probe.
DIGIT_WORDS = {
    "1": "satu",
    "2": "dua",
    "3": "tiga",
    "4": "empat",
    "5": "lima",
    "10": "sepuluh",
    "12": "dua belas",
    "20": "dua puluh",
    "30": "tiga puluh",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--context-limit", type=int, default=5)
    parser.add_argument(
        "--rows",
        type=int,
        nargs="*",
        default=None,
        help="1-based row numbers; default = every row that has a rubric",
    )
    parser.add_argument(
        "--show-answer",
        action="store_true",
        help="Interactive diagnosis only: also print the model's answer text.",
    )
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    # Must match the probe: a cold model returns MODEL_TIMEOUT and its 130-char
    # fallback text, which is easy to misread as "the model answered badly".
    print(f"prewarm_ms={prewarm(cfg):.0f}")
    rows = list(csv.DictReader((PROJECT_ROOT / args.dataset).open(encoding="utf-8")))
    targets = args.rows or sorted(CANDIDATE_RUBRIC)

    retriever = Retriever(
        IndexStore(cfg.resolve_index_path()),
        policy=RetrievalPolicy(context_limit=args.context_limit),
    )
    answer_service = build_answer_service(cfg)

    print(f"context_limit={args.context_limit} rows={len(targets)}")
    print("row|supported|missing_keywords|answer_chars|digit_as_word")
    for number in targets:
        if number < 1 or number > len(rows):
            print(f"{number:02d}|skipped=out_of_range")
            continue
        question = rows[number - 1]["Pertanyaan"]
        required = CANDIDATE_RUBRIC[number]

        retrieval = retriever.retrieve(question)
        answer = answer_service.answer(question, retrieval)
        body = answer.text if hasattr(answer, "text") else str(answer)
        folded = body.casefold()

        missing = [kw for kw in required if kw.casefold() not in folded]
        # Distinguish "wrote the number in words" from "left the fact out".
        spelled = [
            DIGIT_WORDS[kw] for kw in missing if kw in DIGIT_WORDS
            and DIGIT_WORDS[kw] in folded
        ]
        print(
            f"{number:02d}|{answer.supported}|{missing or 'none'}"
            f"|{len(body)}|{spelled or 'no'}"
        )
        if args.show_answer:
            print("   ANSWER: " + " ".join(body.split())[:400])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
