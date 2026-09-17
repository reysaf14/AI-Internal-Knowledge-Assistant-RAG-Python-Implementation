"""M5 local evaluator self-test over synthetic data only.

This is an implementer-level harness test.  It deliberately does not claim
approved 12+3 or Telegram sandbox evidence.
"""
from __future__ import annotations

import time
from pathlib import Path

from rag_assistant.answering.adapter import ChatMessage
from rag_assistant.answering.service import AnswerService
from rag_assistant.evaluation import EvaluationCase, LocalEvaluationRunner
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.index_store import IndexStore


class M5GroundedModel:
    """Synthetic model double with deterministic grounded output."""

    # Extra documents that really exist in the synthetic corpus.  A model that
    # cites one of these alongside the right source is giving a *more* complete
    # answer, which the source contract permits; only the right source is
    # mandatory.
    EXTRA_CITED_DOCUMENTS: tuple[str, ...] = ("04_Kebijakan_Cuti.md",)

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
        citations = [source]
        citations.extend(
            extra
            for extra in self.EXTRA_CITED_DOCUMENTS
            if extra in user_message and extra not in citations
        )
        return f"{body}\nSUMBER: {', '.join(citations)}"


class SlowM5GroundedModel(M5GroundedModel):
    """Synthetic model with bounded work to prove per-case timing isolation."""

    def complete(self, messages: list[ChatMessage], timeout_seconds: float) -> str:
        time.sleep(0.15)
        return super().complete(messages, timeout_seconds)


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
    """Real local pipeline yields sanitized per-case metrics.

    The extra citation in ``EXTRA_CITED_DOCUMENTS`` is deliberate: it proves an
    answer that names the approved source *plus* a second document retrieved from
    the same context is credited, and that a source the model never retrieves is
    still not invented.
    """
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


def test_local_runner_measures_each_case_without_batch_queue_time(
    tmp_path: Path, synthetic_docs: Path
):
    """A bounded model delay in one case must not charge later cases for it."""
    from rag_assistant.config import AppConfig

    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    assert rebuild_corpus(cfg).success
    runner = LocalEvaluationRunner(
        retriever=Retriever(IndexStore(cfg.resolve_index_path())),
        answer_service=AnswerService(SlowM5GroundedModel(), timeout_seconds=1.0),
        state_dir=tmp_path / ".runtime" / "m5-eval",
        max_latency_seconds=0.5,
    )
    supported = tuple(
        EvaluationCase(
            case_id=f"timing-supported-{index}",
            question="Apa saja metode pembayaran yang diterima?",
            expected_supported=True,
            expected_sources=("02_FAQ_Pembayaran.md",),
            expected_answer_terms=("tunai", "QRIS"),
        )
        for index in range(12)
    )
    unsupported = tuple(
        EvaluationCase(
            case_id=f"timing-unsupported-{index}",
            question=f"Pertanyaan di luar corpus {index}",
            expected_supported=False,
        )
        for index in range(3)
    )

    summary = runner.run(supported + unsupported)

    assert summary.latency_passed == 15
    assert all(
        observation.latency_ms is not None and observation.latency_ms < 500
        for observation in summary.observations
    )


def test_source_credit_accepts_a_relevant_extra_and_still_requires_the_key():
    """The source predicate credits a relevant extra without excusing a miss.

    Regression guard for the defect where ``source_pass`` demanded the cited set
    be a *subset* of the approved key.  That failed ``cand-14``, which cites the
    approved policy plus a second document whose "Sakit > 2 Hari Tanpa Surat
    Dokter" section answers the question.  ``AC-017`` requires only that
    additional sources be relevant.
    """
    from rag_assistant.evaluation.runner import source_credit_pass

    key = ("20_Kebijakan_Cuti_dan_Izin_Karyawan.md",)

    # Correct, complete answer: approved key plus a genuinely relevant extra.
    assert source_credit_pass(
        ("20_Kebijakan_Cuti_dan_Izin_Karyawan.md",
         "23_Kebijakan_Sanksi_Pelanggaran.md"),
        key,
    )
    # Exactly the key is still credited.
    assert source_credit_pass(key, key)
    # The mandatory source missing is still a failure, extra or not.
    assert not source_credit_pass(("23_Kebijakan_Sanksi_Pelanggaran.md",), key)
    # Nothing cited is still a failure.
    assert not source_credit_pass((), key)


def test_verdict_gate_uses_the_reported_15_row_content_metric():
    """``REQ-003``'s bar is "at least 12/15", so a 12/15 content run is not FAIL.

    Regression guard for the defect where the verdict compared the 12-row
    ``supported_content_passed`` against 12 while the run reported ``content``
    over 15 rows.  The two disagree whenever an unsupported row misses content,
    which labelled a run FAIL even with all four PRD thresholds met.
    """
    from rag_assistant.evaluation.models import EvaluationSummary

    summary = EvaluationSummary(
        total=15,
        expected_supported=12,
        expected_unsupported=3,
        content_passed=12,           # exactly the PRD bar
        supported_content_passed=9,  # fewer supported rows, more unsupported ones
        source_passed=12,
        abstention_passed=3,
        latency_passed=15,
        responses_sent=15,
        duplicate_responses=0,
        verification_level="local-model",
        acceptance_verdict="NOT_VERIFIED",
    )

    assert summary.metric_targets_match

    # A genuine miss below the bar must still fail the gate.
    below = EvaluationSummary(
        total=15,
        expected_supported=12,
        expected_unsupported=3,
        content_passed=11,
        supported_content_passed=11,
        source_passed=12,
        abstention_passed=3,
        latency_passed=15,
        responses_sent=15,
        duplicate_responses=0,
        verification_level="local-model",
        acceptance_verdict="FAIL",
    )

    assert not below.metric_targets_match

