"""Read-only probe: does a smaller context window raise content accuracy?

Motivation
----------
``diagnose_context_assembly.py`` proved the expected chunk is ranked *first* for
every corpus-compatible row, so the remaining content failures are not a ranking
bug.  The open question is dilution: the same 5-chunk context is handed to the
model regardless of how many of those chunks are actually on-topic, and a 2B
model may latch onto an off-topic passage.

Scope
-----
This is a *measurement*, not a fix.  Every row is answered through the real
M2/M3 path at each candidate ``context_limit``, and only aggregate counts are
printed -- never question text, answer text, or chunk bodies.  Nothing is
written to the index and no approved artefact is modified.

Results feed the ADR that decides whether ``RetrievalPolicy.context_limit``
should change.  The gate parameters (``min_matched_terms``, ``min_coverage``)
are held fixed on purpose: M2's approved gate is not in question here.
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from rag_assistant.answering.service import build_answer_service
from rag_assistant.config import load_config, load_operator_env
from rag_assistant.evaluation import EvaluationCase, LocalEvaluationRunner
from rag_assistant.retrieval.service import RetrievalPolicy, Retriever
from rag_assistant.storage.index_store import IndexStore

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")

# The rubric lives in one place so this probe and run_candidate_eval.py can never
# disagree about what a correct answer looks like.
from candidate_rubric import RUBRIC as CANDIDATE_RUBRIC


def prewarm(cfg) -> float:
    """Load the model before any latency is measured."""
    base = cfg.llm_base_url.rstrip("/").removesuffix("/v1")
    started = time.perf_counter()
    try:
        httpx.post(
            f"{base}/api/chat",
            json={
                "model": cfg.llm_model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "think": False,
                "options": {"num_predict": 1},
            },
            timeout=180.0,
        )
    except httpx.HTTPError:
        pass
    return (time.perf_counter() - started) * 1000


def _cases(dataset: Path, corpus: Path) -> tuple[EvaluationCase, ...]:
    stems = {p.stem for p in corpus.glob("*.md")}
    with dataset.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_HEADERS:
            raise ValueError("dataset headers do not match the approved contract")
        rows = list(reader)

    cases: list[EvaluationCase] = []
    for number, row in enumerate(rows, start=1):
        question = (row.get("Pertanyaan") or "").strip()
        stem = (row.get("Dokumen_Sumber") or "").strip()
        supported = stem in stems
        cases.append(
            EvaluationCase(
                case_id=f"cand-{number:02d}",
                question=question,
                expected_supported=supported,
                expected_sources=(f"{stem}.md",) if supported else (),
                expected_answer_terms=CANDIDATE_RUBRIC.get(number, ())
                if supported
                else (),
            )
        )
    return tuple(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("eval/QA_Dataset_12_3_candidate.csv")
    )
    parser.add_argument(
        "--limits",
        type=int,
        nargs="+",
        default=[1, 2, 3, 5],
        help="context_limit values to compare (default: 1 2 3 5)",
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()
    load_operator_env(root)
    cfg = load_config(root)
    if IndexStore(cfg.resolve_index_path()).get_index_info() is None:
        raise RuntimeError("active index is unavailable or invalid")

    cases = _cases((root / args.dataset).resolve(), cfg.resolve_docs_path())
    state_root = cfg.resolve_index_path().parent

    print(f"prewarm_ms={prewarm(cfg):.0f}")
    print(f"rows={len(cases)}")
    print(
        "context_limit|content|sources|abstention|latency|failing_rows"
    )
    for limit in args.limits:
        runner = LocalEvaluationRunner(
            retriever=Retriever(
                IndexStore(cfg.resolve_index_path()),
                policy=RetrievalPolicy(context_limit=limit),
            ),
            answer_service=build_answer_service(cfg),
            state_dir=Path(state_root),
            verification_level="context-limit-probe",
            max_latency_seconds=5.0,
            poll_timeout_seconds=1,
            max_question_chars=cfg.max_question_chars,
        )
        with TemporaryDirectory(prefix="ctx-probe-", dir=str(state_root)) as state_dir:
            runner._state_dir = Path(state_dir)
            summary = runner.run(cases)

        failing = ",".join(
            obs.case_id for obs in summary.observations if not obs.content_pass
        )
        print(
            f"{limit}|{summary.content_passed}/{summary.total}"
            f"|{summary.source_passed}/{summary.expected_supported}"
            f"|{summary.abstention_passed}/{summary.expected_unsupported}"
            f"|{summary.latency_passed}/{summary.total}"
            f"|{failing or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
