"""M5 local evaluator self-test over synthetic data only.

This is an implementer-level harness test.  It deliberately does not claim
approved 12+3 or Telegram sandbox evidence.
"""
from __future__ import annotations

from pathlib import Path

from rag_assistant.answering.adapter import ChatMessage
from rag_assistant.answering.service import AnswerService
from rag_assistant.evaluation import EvaluationCase, LocalEvaluationRunner
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.index_store import IndexStore


class M5GroundedModel:
    """Synthetic model double with deterministic grounded output."""

    def complete(self, messages: list[ChatMessage], timeout_seconds: float) -> str:
        user_message = messages[1].content
        question = user_message.split("PERTANYAAN:\n", 1)[1].strip()
        if "pembayaran" in question.casefold():
            body = "Pembayaran dapat dilakukan secara tunai dan QRIS."
        else:
            body = "Hak cuti tahunan adalah 12 hari per tahun."
        source = ""
        for line in user_message.splitlines():
            if line.startswith("[Dokumen "):
                source = line.split("] ", 1)[1].split(" | ", 1)[0].strip()
                break
        return f"{body}\nSUMBER: {source}"


def _runner(tmp_path: Path, synthetic_docs: Path) -> LocalEvaluationRunner:
    from rag_assistant.config import AppConfig

    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    assert rebuild_corpus(cfg).success
    return LocalEvaluationRunner(
        retriever=Retriever(IndexStore(cfg.resolve_index_path())),
        answer_service=AnswerService(M5GroundedModel(), timeout_seconds=2.0),
        state_dir=tmp_path / ".runtime" / "m5-eval",
    )


def test_local_runner_measures_latency_sources_and_abstention(
    tmp_path: Path, synthetic_docs: Path
):
    """Real local pipeline yields sanitized per-case metrics."""
    runner = _runner(tmp_path, synthetic_docs)
    cases = (
        EvaluationCase(
            case_id="synthetic-supported-payment",
            question="Apa saja metode pembayaran yang diterima?",
            expected_supported=True,
            expected_sources=("02_FAQ_Pembayaran.md",),
            expected_answer_terms=("tunai", "QRIS"),
        ),
        EvaluationCase(
            case_id="synthetic-supported-leave",
            question="Berapa hari hak cuti tahunan karyawan?",
            expected_supported=True,
            expected_sources=("04_Kebijakan_Cuti.md",),
            expected_answer_terms=("12", "hari"),
        ),
        EvaluationCase(
            case_id="synthetic-unsupported-laundry",
            question="Bagaimana kebijakan layanan laundry antar kota?",
            expected_supported=False,
        ),
    )

    summary = runner.run(cases)

    assert summary.acceptance_verdict == "NOT_VERIFIED"
    assert summary.total == 3
    assert summary.content_passed == 3
    assert summary.supported_content_passed == 2
    assert summary.source_passed == 2
    assert summary.abstention_passed == 1
    assert summary.latency_passed == 3
    assert summary.responses_sent == 3
    assert summary.duplicate_responses == 0
    assert all(item.latency_ms is not None for item in summary.observations)
    assert all(
        item.received_at_epoch_ms is not None
        and item.sent_at_epoch_ms is not None
        and item.sent_at_epoch_ms >= item.received_at_epoch_ms
        for item in summary.observations
    )
    assert all("question" not in repr(item).casefold() for item in summary.observations)


def test_local_runner_checks_m5_target_shape_without_claiming_acceptance(
    tmp_path: Path, synthetic_docs: Path
):
    """A synthetic 12+3 shape passes metrics but remains local-only evidence."""
    runner = _runner(tmp_path, synthetic_docs)
    supported_cases = tuple(
        EvaluationCase(
            case_id=f"synthetic-supported-{index}",
            question=(
                "Apa saja metode pembayaran yang diterima?"
                if index % 2
                else "Berapa hari hak cuti tahunan karyawan?"
            ),
            expected_supported=True,
            expected_sources=(
                ("02_FAQ_Pembayaran.md",)
                if index % 2
                else ("04_Kebijakan_Cuti.md",)
            ),
            expected_answer_terms=(
                ("tunai", "QRIS") if index % 2 else ("12", "hari")
            ),
        )
        for index in range(1, 13)
    )
    unsupported_cases = tuple(
        EvaluationCase(
            case_id=f"synthetic-unsupported-{index}",
            question=f"Pertanyaan di luar corpus nomor {index}?",
            expected_supported=False,
        )
        for index in range(1, 4)
    )

    summary = runner.run(supported_cases + unsupported_cases)

    assert summary.metric_targets_match
    assert summary.acceptance_verdict == "NOT_VERIFIED"
    assert summary.total == 15
    assert summary.supported_content_passed == 12
    assert summary.source_passed == 12
    assert summary.abstention_passed == 3
    assert summary.latency_passed == 15
