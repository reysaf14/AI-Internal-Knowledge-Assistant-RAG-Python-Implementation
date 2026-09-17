"""Run the amended 12+3 eval candidate through the real M2/M3/M4 pipeline.

Local-model metrics only.  ``verification_level="local-model"`` means the
runner can never return PASS here -- the required evidence is the Telegram
sandbox run (AC-027..031).  This script exists to prove the amended dataset
produces matching metrics before the sandbox run is attempted.

Rubric terms are assertion keywords drawn from the approved answer text; the
answer body itself is never printed.
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_assistant.answering.service import build_answer_service
from rag_assistant.config import load_config, load_operator_env
from rag_assistant.evaluation import EvaluationCase, LocalEvaluationRunner
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.index_store import IndexStore


def prewarm_model(cfg) -> tuple[bool, float]:
    """Load the local model into memory before measuring.

    A cold local model needs ~30s to load. The application budget is <5s, so a
    cold call aborts the request, which cancels generation and leaves the model
    cold again -- every later call then times out too. One explicit warm-up
    outside the measured window removes that artifact. This is a runtime
    preparation step, not a measurement of question latency.

    The native ``/api/chat`` endpoint is used because it loads and runs the
    model in ~0.5-1s warm, while the OpenAI-compatible facade takes tens of
    seconds on this runtime.
    """
    import httpx

    base = cfg.llm_base_url.rstrip("/")
    base = base.removesuffix("/v1")
    started = time.perf_counter()
    try:
        response = httpx.post(
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
        return response.status_code < 500, (time.perf_counter() - started) * 1000
    except httpx.HTTPError:
        return False, (time.perf_counter() - started) * 1000

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")

# Row -> assertion terms, from the single shared table (scripts/candidate_rubric.py).
# Two copies of a rubric drift apart, and a rubric that disagrees with itself
# invalidates every comparison made with it.
from candidate_rubric import RUBRIC as CANDIDATE_RUBRIC


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
        if not question or not stem:
            raise ValueError(f"row {number} has an empty required value")
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
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()

    root = Path.cwd().resolve()
    dataset = (root / args.dataset).resolve()
    if not dataset.is_relative_to(root):
        raise ValueError("dataset must remain under the project root")
    if not dataset.is_file():
        raise FileNotFoundError("dataset file was not found")

    load_operator_env(root)
    cfg = load_config(root)
    if IndexStore(cfg.resolve_index_path()).get_index_info() is None:
        raise RuntimeError("active index is unavailable or invalid")

    warmed, warm_ms = prewarm_model(cfg)
    print(f"prewarm_ok={warmed} prewarm_ms={round(warm_ms)}")

    cases = _cases(dataset, cfg.resolve_docs_path())
    state_root = cfg.resolve_index_path().parent
    runner = LocalEvaluationRunner(
        retriever=Retriever(IndexStore(cfg.resolve_index_path())),
        answer_service=build_answer_service(cfg),
        state_dir=Path(state_root),
        verification_level="local-model",
        max_latency_seconds=5.0,
        poll_timeout_seconds=1,
        max_question_chars=cfg.max_question_chars,
    )

    started = time.perf_counter()
    with TemporaryDirectory(prefix="m5-candidate-", dir=str(state_root)) as state_dir:
        runner._state_dir = Path(state_dir)
        summary = runner.run(cases)

    print(f"shape={summary.expected_supported}+{summary.expected_unsupported}")
    print(f"content={summary.content_passed}/{summary.total}")
    print(f"supported_content={summary.supported_content_passed}/{summary.expected_supported}")
    print(f"sources={summary.source_passed}/{summary.expected_supported}")
    print(f"abstention={summary.abstention_passed}/{summary.expected_unsupported}")
    print(f"latency={summary.latency_passed}/{summary.total}")
    print(f"sent={summary.responses_sent} duplicates={summary.duplicate_responses}")
    print(f"wall_ms={round((time.perf_counter() - started) * 1000, 1)}")
    print(f"verification_level={summary.verification_level}")
    print(f"acceptance_verdict={summary.acceptance_verdict}")
    for obs in summary.observations:
        lat = f"{obs.latency_ms:.1f}ms" if obs.latency_ms is not None else "none"
        print(
            f"{obs.case_id}|supported={obs.expected_supported}|content={obs.content_pass}|"
            f"source={obs.source_pass}|abstention={obs.abstention_pass}|latency={lat}|"
            f"failures={','.join(obs.failure_categories) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
