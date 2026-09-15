"""Telegram polling loop: fetch, deduplicate, validate, answer, send.

The ordering here *is* the M4 contract:

1. **deduplicate** by update id  -> at most one answer per update identity
2. **claim** the update before any observable action -> a crash between send and
   bookkeeping cannot produce a second answer for the same identity
3. **validate** the update -> a rejection never reaches retrieval or a model
4. **send** and record the truthful outcome (``sent`` / ``unknown`` / ``failed``)

The loop never reports success for an undecidable send, never dies on a polling
failure (bounded backoff instead), and logs only technical metadata -- never the
question, the answer, the chat id, or a raw payload.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rag_assistant.answering.prompts import format_answer
from rag_assistant.answering.service import AnswerService
from rag_assistant.observability.logger import SanitizedLogger
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram import policy
from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
    TelegramBoundary,
    TelegramError,
)
from rag_assistant.telegram.validation import (
    UpdateKind,
    ValidationDecision,
    validate_update,
)

LOGGER_NAME = "rag_assistant.telegram"

STATUS_CLAIMED = "claimed"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"
STATUS_HELP = "help"
STATUS_ANSWERED = "answered"


@dataclass
class PollCounters:
    """Technical counters for one run. Never contains message content."""

    attempts: int = 0
    polls: int = 0
    updates: int = 0
    answers_delivered: int = 0
    duplicates: int = 0
    rejected: int = 0
    sends_failed: int = 0
    sends_unknown: int = 0
    poll_failures: int = 0
    pruned: int = 0


class TelegramPoller:
    """Drive the Telegram long-poll loop over a swappable boundary."""

    def __init__(
        self,
        *,
        boundary: TelegramBoundary,
        state_store: StateStore,
        retriever: Retriever,
        answer_service: AnswerService,
        poll_timeout_seconds: int = 30,
        max_question_chars: int = 2000,
        retention_days: int = policy.PROCESSED_UPDATE_RETENTION_DAYS,
        poll_interval_seconds: float = 0.0,
        max_iterations: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: SanitizedLogger | None = None,
    ) -> None:
        if poll_timeout_seconds < 1:
            raise ValueError("poll_timeout_seconds must be positive")
        if max_question_chars < 1:
            raise ValueError("max_question_chars must be positive")
        self._boundary = boundary
        self._state = state_store
        self._retriever = retriever
        self._answer_service = answer_service
        self._poll_timeout = poll_timeout_seconds
        self._max_question_chars = max_question_chars
        self._retention_days = retention_days
        self._poll_interval = max(poll_interval_seconds, 0.0)
        self._max_iterations = max_iterations
        self._sleep = sleep
        self._logger = logger or SanitizedLogger(LOGGER_NAME)
        self._consecutive_poll_failures = 0
        self.counters = PollCounters()

    def run(self) -> PollCounters:
        """Run the polling loop until the optional iteration cap is reached."""
        self._prune()
        while self._max_iterations is None or self.counters.attempts < self._max_iterations:
            self.counters.attempts += 1
            try:
                updates = self._boundary.get_updates(
                    self._state.get_polling_offset(), self._poll_timeout
                )
            except TelegramError as exc:
                self._handle_poll_failure(exc)
                continue

            self._consecutive_poll_failures = 0
            self.counters.polls += 1
            self.process_batch(updates)

            if self.counters.polls % policy.PRUNE_EVERY_N_POLLS == 0:
                self._prune()
            if self._poll_interval:
                self._sleep(self._poll_interval)
        return self.counters

    def process_batch(self, updates: Sequence[IncomingUpdate]) -> int:
        """Handle one batch in order, advancing the offset per handled update."""
        next_offset = self._state.get_polling_offset()
        for update in updates:
            self.counters.updates += 1
            try:
                self.handle_update(update)
            except Exception:  # noqa: BLE001 - one bad update must not kill the batch
                self._logger.log_operation(
                    operation="update",
                    status="error",
                    error_category="UNHANDLED_UPDATE_ERROR",
                )
            next_offset = max(next_offset, update.update_id + 1)
            self._state.set_polling_offset(next_offset)
        return next_offset

    def handle_update(self, update: IncomingUpdate) -> str:
        """Handle a single update and return its technical status."""
        if self._state.is_update_processed(update.update_id):
            self.counters.duplicates += 1
            self._logger.log_operation(
                operation="update", status=STATUS_DUPLICATE, reason="already_processed"
            )
            return STATUS_DUPLICATE

        # Claim before any observable action so a crash cannot answer twice.
        self._state.mark_update_processed(update.update_id, status=STATUS_CLAIMED)

        decision = validate_update(update, self._max_question_chars)
        if decision.kind is UpdateKind.REJECTED:
            self.counters.rejected += 1
            return self._deliver(update, decision.safe_reply, STATUS_REJECTED)
        if decision.kind is UpdateKind.HELP:
            return self._deliver(update, decision.safe_reply, STATUS_HELP)
        return self._answer(update, decision)

    def _deliver(self, update: IncomingUpdate, text: str, status: str) -> str:
        """Send one canned reply when a reply is possible and non-empty."""
        if not text or not update.chat_id:
            self._state.set_update_status(update.update_id, status)
            self._log_update(status)
            return status
        result = self._boundary.send_message(update.chat_id, text)
        self._record_send(update.update_id, result)
        self._log_update(status, reason=result.outcome.value)
        return status

    def _answer(self, update: IncomingUpdate, decision: ValidationDecision) -> str:
        """Retrieve, answer, and deliver for an accepted question."""
        retrieval = self._retriever.retrieve(decision.question)
        answer = self._answer_service.answer(decision.question, retrieval)
        result = self._boundary.send_message(update.chat_id, format_answer(answer))
        self._record_send(update.update_id, result)
        if result.is_success:
            self.counters.answers_delivered += 1
        self._log_update(
            STATUS_ANSWERED if result.is_success else "answer_not_delivered",
            reason=result.outcome.value,
            corpus_version=retrieval.corpus_version,
            supported=str(answer.supported),
        )
        return result.outcome.value

    def _record_send(self, update_id: int, result: SendResult) -> None:
        if result.outcome is SendOutcome.UNKNOWN:
            self.counters.sends_unknown += 1
        elif result.outcome is SendOutcome.FAILED:
            self.counters.sends_failed += 1
        self._state.set_update_status(update_id, result.outcome.value)
        self._logger.log_operation(
            operation="send",
            status=result.outcome.value,
            error_category=result.error_category,
            attempts=str(result.attempts),
        )

    def _handle_poll_failure(self, exc: TelegramError) -> None:
        self._consecutive_poll_failures += 1
        self.counters.poll_failures += 1
        delay = self._backoff_delay()
        self._logger.log_operation(
            operation="poll",
            status="error",
            error_category=exc.category,
            backoff_s=f"{delay:.1f}",
        )
        self._sleep(delay)

    def _backoff_delay(self) -> float:
        shift = min(self._consecutive_poll_failures - 1, policy.BACKOFF_MAX_SHIFT)
        delay = policy.BACKOFF_INITIAL_SECONDS * (policy.BACKOFF_MULTIPLIER**shift)
        return min(delay, policy.BACKOFF_MAX_SECONDS)

    def _prune(self) -> None:
        removed = self._state.prune_processed_updates(self._retention_days)
        if removed:
            self.counters.pruned += removed
            self._logger.log_operation(
                operation="state_prune", status="ok", removed=str(removed)
            )

    def _log_update(self, status: str, **metadata: str) -> None:
        self._logger.log_operation(operation="update", status=status, **metadata)
