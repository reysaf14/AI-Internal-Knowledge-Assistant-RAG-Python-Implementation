"""Run a sanitized local-model evaluation over the supplied CSV.

This command is intentionally an exploratory bridge for the currently
approved input file. It derives supported/unsupported shape from whether the
referenced source exists in the approved corpus and uses a small conservative
term rubric for local smoke evidence. It cannot replace Human approval of the
final 12+3 rubric or Telegram sandbox evidence.
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

EXPECTED_HEADERS = ("Pertanyaan", "Jawaban_Benar", "Dokumen_Sumber")

# Conservative local-smoke terms, not the final approved content rubric.
# Values contain only short assertion terms; answer text is never printed.
LOCAL_SMOKE_TERMS: dict[int, tuple[str, ...]] = {
    1: ("21", "tutup"),
    2: ("12", "cuti"),
    4: ("500.000", "bonus"),
    5: ("3", "struk"),
    6: ("tunai", "QRIS", "debit"),
    9: ("GRN", "foto", "retur"),
    10: ("belum", "2027"),
    11: ("1 jam", "50.000"),
    12: ("950.000", "bonus"),
    13: ("diskon", "expired"),
    14: ("sakit", "cuti"),
}


def _parse_cases(dataset_path: Path, corpus_path: Path) -> tuple[EvaluationCase, ...]:
    corpus_stems = {path.stem for path in corpus_path.glob("*.md")}
    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_HEADERS:
            raise ValueError("dataset headers do not match the approved contract")
        rows = list(reader)

    cases: list[EvaluationCase] = []
    for row_number, row in enumerate(rows, start=1):
        question = (row.get("Pertanyaan") or "").strip()
        source_stem = (row.get("Dokumen_Sumber") or "").strip()
        if not question or not source_stem:
            raise ValueError(f"dataset row {row_number} has an empty required value")
        source = f"{source_stem}.md"
        supported = source_stem in corpus_stems
        cases.append(
            EvaluationCase(
                case_id=f"csv-{row_number:02d}",
                question=question,
                expected_supported=supported,
                expected_sources=(source,) if supported else (),
                expected_answer_terms=LOCAL_SMOKE_TERMS.get(row_number, ())
                if supported
                else (),
            )
        )
    return tuple(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("eval/QA_Dataset_15_Pasangan.csv"),
    )
    args = parser.parse_args()
    project_root = Path.cwd().resolve()
    dataset_path = (project_root / args.dataset).resolve()
    if not dataset_path.is_relative_to(project_root):
        raise ValueError("dataset must remain under the project root")
    if not dataset_path.is_file():
        raise FileNotFoundError("dataset file was not found")

    load_operator_env(project_root)
    config = load_config(project_root)
    index_info = IndexStore(config.resolve_index_path()).get_index_info()
    if index_info is None:
        raise RuntimeError("active index is unavailable or invalid")

    cases = _parse_cases(dataset_path, config.resolve_docs_path())
    state_root = config.resolve_index_path().parent
    retriever = Retriever(IndexStore(config.resolve_index_path()))
    answer_service = build_answer_service(config)

    started = time.perf_counter()
    with TemporaryDirectory(prefix="m5-csv-eval-", dir=str(state_root)) as state_dir:
        runner = LocalEvaluationRunner(
            retriever=retriever,
            answer_service=answer_service,
            state_dir=Path(state_dir),
            verification_level="local-model",
            max_latency_seconds=5.0,
            poll_timeout_seconds=1,
            max_question_chars=config.max_question_chars,
        )
        summary = runner.run(cases)

    print(f"dataset_rows={summary.total}")
    print(
        "shape="
        f"{summary.expected_supported} supported + "
        f"{summary.expected_unsupported} unsupported"
    )
    print(f"content={summary.content_passed}/{summary.total}")
    print(
        f"supported_content={summary.supported_content_passed}/"
        f"{summary.expected_supported}"
    )
    print(f"sources={summary.source_passed}/{summary.expected_supported}")
    print(f"abstention={summary.abstention_passed}/{summary.expected_unsupported}")
    print(f"latency={summary.latency_passed}/{summary.total}")
    print(f"sent={summary.responses_sent} duplicates={summary.duplicate_responses}")
    print(f"wall_ms={round((time.perf_counter() - started) * 1000, 1)}")
    print(f"verification_level={summary.verification_level}")
    print(f"acceptance_verdict={summary.acceptance_verdict}")
    for observation in summary.observations:
        latency = (
            f"{observation.latency_ms:.1f}ms"
            if observation.latency_ms is not None
            else "none"
        )
        print(
            f"{observation.case_id}|supported={observation.expected_supported}|"
            f"content={observation.content_pass}|source={observation.source_pass}|"
            f"abstention={observation.abstention_pass}|latency={latency}|"
            f"failures={','.join(observation.failure_categories) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
