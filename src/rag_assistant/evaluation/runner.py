"""Local M5 runner over the real retrieval, answering, and polling path.

This module is intentionally boundary-injected.  ``TimedLocalBoundary`` is a
synthetic Telegram boundary for deterministic self-tests; it is not evidence
of Telegram sandbox delivery.  A sandbox adapter can implement the same
protocol later without changing the metric collection or rubric evaluation.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

from rag_assistant.answering.prompts import ABSTENTION_TEXT
from rag_assistant.answering.service import AnswerService
from rag_assistant.answering.validator import extract_claimed_sources, strip_source_line
from rag_assistant.evaluation.models import (
    EvaluationCase,
    EvaluationObservation,
    EvaluationSummary,
)
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
)
from rag_assistant.telegram.poller import TelegramPoller


class TimedLocalBoundary:
    """Deterministic local Telegram boundary with receive-to-send timestamps."""

    def __init__(self, updates: Sequence[IncomingUpdate]) -> None:
        self._updates = tuple(updates)
        self._update_by_chat_id = {
            update.chat_id: update.update_id for update in self._updates
        }
        self.received_at: float | None = None
        self.sent_at: float | None = None
        self.received_at_epoch_ms: int | None = None
        self.sent_at_epoch_ms: int | None = None
        self.sent_messages: list[str] = []
        self.send_outcomes: list[SendOutcome] = []
        self.received_at_by_update: dict[int, float] = {}
        self.sent_at_by_update: dict[int, float] = {}
        self.received_at_epoch_ms_by_update: dict[int, int] = {}
        self.sent_at_epoch_ms_by_update: dict[int, int] = {}
        self.sent_messages_by_update: dict[int, list[str]] = {}
        self.send_outcomes_by_update: dict[int, list[SendOutcome]] = {}

    def get_updates(
        self, offset: int, timeout_seconds: int
    ) -> Sequence[IncomingUpdate]:
        eligible = tuple(
            update for update in self._updates if update.update_id >= offset
        )
        if eligible:
            received_at = time.perf_counter()
            received_at_epoch_ms = time.time_ns() // 1_000_000
            self.received_at = self.received_at or received_at
            self.received_at_epoch_ms = self.received_at_epoch_ms or received_at_epoch_ms
            for update in eligible:
                self.received_at_by_update[update.update_id] = received_at
                self.received_at_epoch_ms_by_update[update.update_id] = received_at_epoch_ms
        return eligible

    def send_message(self, chat_id: str, text: str) -> SendResult:
        sent_at = time.perf_counter()
        sent_at_epoch_ms = time.time_ns() // 1_000_000
        self.sent_at = sent_at
        self.sent_at_epoch_ms = sent_at_epoch_ms
        self.sent_messages.append(text)
        self.send_outcomes.append(SendOutcome.SENT)
        update_id = self._update_by_chat_id.get(chat_id)
        if update_id is not None:
            self.sent_at_by_update[update_id] = sent_at
            self.sent_at_epoch_ms_by_update[update_id] = sent_at_epoch_ms
            self.sent_messages_by_update.setdefault(update_id, []).append(text)
            self.send_outcomes_by_update.setdefault(update_id, []).append(
                SendOutcome.SENT
            )
        return SendResult(SendOutcome.SENT, attempts=1)


class LocalEvaluationRunner:
    """Run cases through the real M2/M3/M4 application path.

    ``verification_level`` defaults to ``local-mock`` so passing local
    metrics can never be mistaken for the required Telegram sandbox evidence.
    """

    def __init__(
        self,
        *,
        retriever: Retriever,
        answer_service: AnswerService,
        state_dir: Path,
        max_latency_seconds: float = 5.0,
        verification_level: str = "local-mock",
        poll_timeout_seconds: int = 1,
        max_question_chars: int = 2000,
    ) -> None:
        if max_latency_seconds <= 0:
            raise ValueError("max_latency_seconds must be positive")
        if not verification_level.strip():
            raise ValueError("verification_level must not be empty")
        self._retriever = retriever
        self._answer_service = answer_service
        self._state_dir = state_dir
        self._max_latency_seconds = float(max_latency_seconds)
        self._verification_level = verification_level
        self._poll_timeout_seconds = poll_timeout_seconds
        self._max_question_chars = max_question_chars

    def run(
        self,
        cases: Sequence[EvaluationCase],
        *,
        update_id_start: int = 1,
        chat_id: str = "synthetic-chat",
        sleep: Callable[[float], None] | None = None,
    ) -> EvaluationSummary:
        """Evaluate cases and return sanitized per-case plus aggregate evidence."""
        self._validate_cases(cases)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        observations: list[EvaluationObservation] = []

        updates = tuple(
            IncomingUpdate(update_id_start + index, f"{chat_id}-{index}", case.question)
            for index, case in enumerate(cases)
        )
        boundary = TimedLocalBoundary(updates)
        poller = TelegramPoller(
            boundary=boundary,
            state_store=StateStore(self._state_dir / "polling-state.sqlite3"),
            retriever=self._retriever,
            answer_service=self._answer_service,
            poll_timeout_seconds=self._poll_timeout_seconds,
            max_question_chars=self._max_question_chars,
            max_iterations=1,
            sleep=sleep or (lambda _seconds: None),
        )
        poller.run()
        for case, update in zip(cases, updates, strict=True):
            observations.append(self._observe(case, boundary, update.update_id))

        return self._summarize(observations)

    @staticmethod
    def _validate_cases(cases: Sequence[EvaluationCase]) -> None:
        if not cases:
            raise ValueError("at least one evaluation case is required")
        ids = [case.case_id for case in cases]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation case IDs must be unique")

    def _observe(
        self, case: EvaluationCase, boundary: TimedLocalBoundary, update_id: int
    ) -> EvaluationObservation:
        messages = boundary.sent_messages_by_update.get(update_id, [])
        message = messages[0] if messages else ""
        sources = extract_claimed_sources(message)
        abstained = message.strip() == ABSTENTION_TEXT
        supported = bool(sources) and not abstained
        response_count = len(messages)
        outcomes = boundary.send_outcomes_by_update.get(update_id, [])
        outcome = outcomes[0].value if outcomes else "not_sent"
        received_at = boundary.received_at_by_update.get(update_id)
        sent_at = boundary.sent_at_by_update.get(update_id)
        latency_ms = None
        if received_at is not None and sent_at is not None:
            latency_ms = (sent_at - received_at) * 1000

        body = strip_source_line(message).casefold()
        if case.expected_supported:
            content_pass = supported and all(
                term.casefold() in body for term in case.expected_answer_terms
            )
            source_pass = (
                bool(sources)
                and bool(set(sources).intersection(case.expected_sources))
                and all(source in case.expected_sources for source in sources)
            )
            abstention_pass = not abstained and supported
        else:
            content_pass = abstained and not sources
            source_pass = not sources
            abstention_pass = abstained and not sources

        latency_pass = latency_ms is not None and latency_ms < (
            self._max_latency_seconds * 1000
        )
        failures: list[str] = []
        if not content_pass:
            failures.append("content")
        if not source_pass:
            failures.append("source")
        if not abstention_pass:
            failures.append("abstention")
        if not latency_pass:
            failures.append("latency")
        if response_count != 1:
            failures.append("response_count")

        return EvaluationObservation(
            case_id=case.case_id,
            expected_supported=case.expected_supported,
            observed_supported=supported,
            observed_abstained=abstained,
            observed_sources=sources,
            send_outcome=outcome,
            response_count=response_count,
            received_at_epoch_ms=boundary.received_at_epoch_ms_by_update.get(update_id),
            sent_at_epoch_ms=boundary.sent_at_epoch_ms_by_update.get(update_id),
            latency_ms=latency_ms,
            content_pass=content_pass,
            source_pass=source_pass,
            abstention_pass=abstention_pass,
            latency_pass=latency_pass,
            failure_categories=tuple(failures),
        )

    def _summarize(
        self, observations: Sequence[EvaluationObservation]
    ) -> EvaluationSummary:
        total = len(observations)
        expected_supported = sum(item.expected_supported for item in observations)
        expected_unsupported = total - expected_supported
        content_passed = sum(item.content_pass for item in observations)
        supported_content_passed = sum(
            item.content_pass for item in observations if item.expected_supported
        )
        source_passed = sum(
            item.source_pass for item in observations if item.expected_supported
        )
        abstention_passed = sum(
            item.abstention_pass for item in observations if not item.expected_supported
        )
        latency_passed = sum(item.latency_pass for item in observations)
        responses_sent = sum(
            item.send_outcome == SendOutcome.SENT.value for item in observations
        )
        duplicate_responses = sum(
            max(item.response_count - 1, 0) for item in observations
        )

        metrics_match = (
            total == 15
            and expected_supported == 12
            and expected_unsupported == 3
            and supported_content_passed >= expected_supported
            and source_passed == expected_supported
            and abstention_passed == expected_unsupported
            and latency_passed == total
            and responses_sent == total
            and duplicate_responses == 0
        )
        if not metrics_match:
            verdict = "NOT_VERIFIED" if total != 15 else "FAIL"
        elif self._verification_level != "telegram-sandbox":
            verdict = "NOT_VERIFIED"
        else:
            verdict = "PASS"

        return EvaluationSummary(
            total=total,
            expected_supported=expected_supported,
            expected_unsupported=expected_unsupported,
            content_passed=content_passed,
            supported_content_passed=supported_content_passed,
            source_passed=source_passed,
            abstention_passed=abstention_passed,
            latency_passed=latency_passed,
            responses_sent=responses_sent,
            duplicate_responses=duplicate_responses,
            verification_level=self._verification_level,
            acceptance_verdict=verdict,
            observations=tuple(observations),
        )
