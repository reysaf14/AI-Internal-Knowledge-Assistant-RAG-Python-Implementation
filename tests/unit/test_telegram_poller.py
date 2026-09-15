"""M4 unit tests: deduplication, rejection ordering, send outcomes, backoff.

Covers AC-007 (reject before retrieval/model), AC-008/014/019/024 (one answer
per update identity), AC-009 (bounded backoff, no fake success), AC-010 (truthful
send outcome) -- all at the mock boundary, with no token and no network.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from rag_assistant.domain.types import AnswerResult, RetrievalResult, SupportLevel
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
    TelegramUnavailable,
)
from rag_assistant.telegram.poller import TelegramPoller
from rag_assistant.telegram.validation import HELP_TEXT, REPLY_EMPTY

ANSWERED = AnswerResult(
    text="Toko menerima tunai dan QRIS.",
    sources=["02_FAQ_Pembayaran.md"],
    supported=True,
    abstained=False,
)
SUPPORTED = RetrievalResult(
    support_level=SupportLevel.SUFFICIENT, corpus_version="synthetic-v1"
)


class FakeBoundary:
    """Local Telegram double that records exactly what it was asked to send."""

    def __init__(self, batches=None, failures=0, outcome=SendOutcome.SENT):
        self._batches = [list(batch) for batch in (batches or [])]
        self._failures = failures
        self._outcome = outcome
        self.sent: list[tuple[str, str]] = []
        self.get_updates_calls = 0

    def get_updates(self, offset, timeout_seconds):
        """Return the next scripted batch, or raise a scripted outage."""
        self.get_updates_calls += 1
        if self._failures > 0:
            self._failures -= 1
            raise TelegramUnavailable("synthetic outage")
        if self._batches:
            return tuple(self._batches.pop(0))
        return ()

    def send_message(self, chat_id, text):
        """Record the send and report the scripted outcome."""
        self.sent.append((chat_id, text))
        category = "" if self._outcome is SendOutcome.SENT else "SYNTHETIC"
        return SendResult(self._outcome, attempts=1, error_category=category)


class SpyRetriever:
    """Counts retrieval calls so a rejection can be proven not to reach it."""

    def __init__(self):
        self.calls = 0

    def retrieve(self, query):
        """Count and return a supported result."""
        self.calls += 1
        return SUPPORTED


class SpyAnswerService:
    """Counts answer calls so ordering guarantees are observable."""

    def __init__(self):
        self.calls = 0

    def answer(self, question, retrieval):
        """Count and return a canned grounded answer."""
        self.calls += 1
        return ANSWERED


def _build(tmp_path: Path, boundary, retriever=None, answer=None, **kwargs):
    sleeps: list[float] = []
    poller = TelegramPoller(
        boundary=boundary,
        state_store=StateStore(tmp_path / "state.sqlite3"),
        retriever=retriever or SpyRetriever(),
        answer_service=answer or SpyAnswerService(),
        sleep=sleeps.append,
        **kwargs,
    )
    return poller, sleeps


def _question(text: str = "metode pembayaran", update_id: int = 10):
    return IncomingUpdate(update_id=update_id, chat_id="555", text=text)


def test_valid_update_produces_exactly_one_response(tmp_path: Path):
    """AC-006 (mock level): one valid update yields one delivered response."""
    boundary = FakeBoundary(batches=[[_question()]])
    retriever, answer = SpyRetriever(), SpyAnswerService()
    poller, _ = _build(tmp_path, boundary, retriever, answer, max_iterations=1)

    poller.run()

    assert poller.counters.answers_delivered == 1
    assert len(boundary.sent) == 1
    assert retriever.calls == 1
    assert answer.calls == 1
    assert boundary.sent[0][1] == "Toko menerima tunai dan QRIS.\n\nSumber: 02_FAQ_Pembayaran.md"


def test_duplicate_redelivery_never_answers_twice(tmp_path: Path):
    """AC-008/014/019/024: the same update identity yields one message only."""
    update = _question(update_id=42)
    boundary = FakeBoundary(batches=[[update], [update]])
    retriever, answer = SpyRetriever(), SpyAnswerService()
    poller, _ = _build(tmp_path, boundary, retriever, answer, max_iterations=2)

    poller.run()

    assert len(boundary.sent) == 1
    assert answer.calls == 1
    assert poller.counters.duplicates == 1


def test_deduplication_survives_a_restart(tmp_path: Path):
    """A restarted process must not re-answer an already handled update."""
    update = _question(update_id=77)
    first_boundary = FakeBoundary(batches=[[update]])
    first, _ = _build(tmp_path, first_boundary, max_iterations=1)
    first.run()
    assert len(first_boundary.sent) == 1

    # New process, same state file, Telegram redelivers the same update.
    second_boundary = FakeBoundary(batches=[[update]])
    second, _ = _build(tmp_path, second_boundary, max_iterations=1)
    second.run()

    assert second_boundary.sent == []
    assert second.counters.duplicates == 1


def test_rejection_never_reaches_retrieval_or_model(tmp_path: Path):
    """AC-007: an invalid update is refused before any corpus or model access."""
    boundary = FakeBoundary(batches=[[_question("", update_id=5)]])
    retriever, answer = SpyRetriever(), SpyAnswerService()
    poller, _ = _build(tmp_path, boundary, retriever, answer, max_iterations=1)

    poller.run()

    assert retriever.calls == 0
    assert answer.calls == 0
    assert poller.counters.rejected == 1
    assert boundary.sent == [("555", REPLY_EMPTY)]


def test_help_command_is_answered_locally(tmp_path: Path):
    """A command is handled without reading the corpus."""
    boundary = FakeBoundary(batches=[[_question("/help", update_id=6)]])
    retriever, answer = SpyRetriever(), SpyAnswerService()
    poller, _ = _build(tmp_path, boundary, retriever, answer, max_iterations=1)

    poller.run()

    assert boundary.sent == [("555", HELP_TEXT)]
    assert retriever.calls == 0
    assert answer.calls == 0
    assert poller.counters.answers_delivered == 0


def test_non_text_update_is_rejected_without_a_model_call(tmp_path: Path):
    """A photo/sticker update carries no text and is refused."""
    boundary = FakeBoundary(
        batches=[[IncomingUpdate(update_id=8, chat_id="555", text=None)]]
    )
    retriever, answer = SpyRetriever(), SpyAnswerService()
    poller, _ = _build(tmp_path, boundary, retriever, answer, max_iterations=1)

    poller.run()

    assert retriever.calls == 0
    assert answer.calls == 0
    assert poller.counters.rejected == 1
    assert len(boundary.sent) == 1


def test_undecidable_send_is_recorded_as_unknown_not_success(tmp_path: Path):
    """AC-010: an unknown send result can never be reported as success."""
    boundary = FakeBoundary(batches=[[_question()]], outcome=SendOutcome.UNKNOWN)
    poller, _ = _build(tmp_path, boundary, max_iterations=1)

    poller.run()

    assert poller.counters.sends_unknown == 1
    assert poller.counters.answers_delivered == 0
    conn = sqlite3.connect(str(tmp_path / "state.sqlite3"))
    status = conn.execute(
        "SELECT status FROM processed_updates WHERE update_id = 10"
    ).fetchone()[0]
    conn.close()
    assert status == "unknown"


def test_rejected_send_is_recorded_as_failed(tmp_path: Path):
    """A definitive rejection is recorded as failed, not as sent."""
    boundary = FakeBoundary(batches=[[_question()]], outcome=SendOutcome.FAILED)
    poller, _ = _build(tmp_path, boundary, max_iterations=1)

    poller.run()

    assert poller.counters.sends_failed == 1
    assert poller.counters.answers_delivered == 0


def test_polling_failure_backs_off_and_keeps_running(tmp_path: Path):
    """AC-009: a transport outage backs off and never produces a fake answer."""
    boundary = FakeBoundary(batches=[[_question()]], failures=3)
    poller, sleeps = _build(tmp_path, boundary, max_iterations=4)

    poller.run()

    assert sleeps == [1.0, 2.0, 4.0]
    assert poller.counters.poll_failures == 3
    assert poller.counters.answers_delivered == 1
    assert len(boundary.sent) == 1


def test_backoff_is_capped(tmp_path: Path):
    """Backoff grows but stays bounded instead of exploding."""
    boundary = FakeBoundary(failures=40)
    poller, sleeps = _build(tmp_path, boundary, max_iterations=12)

    poller.run()

    assert max(sleeps) == 30.0
    assert sleeps[0] == 1.0


def test_offset_advances_past_each_handled_update(tmp_path: Path):
    """The polling offset moves only as far as updates we actually handled."""
    boundary = FakeBoundary(
        batches=[[_question(update_id=100), _question(update_id=101)]]
    )
    poller, _ = _build(tmp_path, boundary, max_iterations=1)

    poller.run()

    assert poller._state.get_polling_offset() == 102


def test_logs_never_contain_question_or_answer_text(tmp_path: Path, caplog):
    """Sanitized observability: no message content reaches the log."""
    question_marker = "MARKERQ5678"
    answer_marker = "MARKERA5678"
    boundary = FakeBoundary(batches=[[_question(f"metode pembayaran {question_marker}")]])
    answered = AnswerResult(
        text=f"{answer_marker} tunai dan QRIS.",
        sources=["02_FAQ_Pembayaran.md"],
        supported=True,
        abstained=False,
    )
    poller, _ = _build(
        tmp_path, boundary, answer=SpyAnswerService(), max_iterations=1
    )
    poller._answer_service = _FixedAnswer(answered)

    with caplog.at_level(logging.INFO):
        poller.run()

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert question_marker not in logged
    assert answer_marker not in logged
    assert "op=update" in logged


class _FixedAnswer:
    """Answer double that returns a specific result and counts calls."""

    def __init__(self, result: AnswerResult):
        self.calls = 0
        self._result = result

    def answer(self, question, retrieval):
        """Return the fixed result."""
        self.calls += 1
        return self._result
