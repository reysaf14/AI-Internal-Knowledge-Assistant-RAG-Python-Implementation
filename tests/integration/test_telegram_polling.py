"""M4 integration: the real retrieval + answering path over a mock boundary.

The Telegram boundary is a local double (no token, no network), while the
retriever, the index, the support gate, and the answer validator are the real
M2/M3 implementations. This proves the M4 wiring end to end at mock level; the
Telegram sandbox level stays pending until a token is provided.
"""
from __future__ import annotations

from pathlib import Path

from rag_assistant.answering.service import AnswerService
from rag_assistant.config import AppConfig
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.index_store import IndexStore
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
)
from rag_assistant.telegram.poller import TelegramPoller

SUPPORTED_QUESTION = "Apa saja metode pembayaran yang diterima?"
UNSUPPORTED_QUESTION = "Bagaimana kebijakan layanan laundry antar kota?"


class FakeBoundary:
    """Local Telegram double used for the whole scenario."""

    def __init__(self, batches, outcome=SendOutcome.SENT):
        self._batches = [list(batch) for batch in batches]
        self._outcome = outcome
        self.sent: list[tuple[str, str]] = []

    def get_updates(self, offset, timeout_seconds):
        """Return the next scripted batch."""
        if self._batches:
            return tuple(self._batches.pop(0))
        return ()

    def send_message(self, chat_id, text):
        """Record the outbound message."""
        self.sent.append((chat_id, text))
        return SendResult(self._outcome, attempts=1)


class GroundedModel:
    """Deterministic model double that cites the first in-context document."""

    def complete(self, messages, timeout_seconds):
        """Echo the first context document as the SUMBOR line."""
        user = messages[1].content
        source = ""
        for line in user.splitlines():
            if line.startswith("[Dokumen "):
                source = line.split("] ", 1)[1].split(" | ", 1)[0].strip()
                break
        return f"Toko menerima pembayaran sesuai dokumen resmi.\nSUMBER: {source}"


def _poller(tmp_path: Path, synthetic_docs: Path, boundary, max_iterations=1):
    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    assert rebuild_corpus(cfg).success
    poller = TelegramPoller(
        boundary=boundary,
        state_store=StateStore(tmp_path / ".runtime" / "bot_state.sqlite3"),
        retriever=Retriever(IndexStore(cfg.resolve_index_path())),
        answer_service=AnswerService(GroundedModel(), timeout_seconds=2.0),
        max_iterations=max_iterations,
        sleep=lambda _seconds: None,
    )
    return poller


def test_supported_question_is_answered_with_a_source(tmp_path: Path, synthetic_docs: Path):
    """AC-006/017 at mock level: one update yields one sourced response."""
    boundary = FakeBoundary([[IncomingUpdate(1, "555", SUPPORTED_QUESTION)]])
    poller = _poller(tmp_path, synthetic_docs, boundary)

    poller.run()

    assert len(boundary.sent) == 1
    _chat_id, text = boundary.sent[0]
    assert "Sumber: 02_FAQ_Pembayaran.md" in text
    assert poller.counters.answers_delivered == 1


def test_unsupported_question_abstains_without_sources(tmp_path: Path, synthetic_docs: Path):
    """AC-022 at mock level: an unsupported question abstains, no fake source."""
    boundary = FakeBoundary([[IncomingUpdate(2, "555", UNSUPPORTED_QUESTION)]])
    poller = _poller(tmp_path, synthetic_docs, boundary)

    poller.run()

    assert len(boundary.sent) == 1
    _chat_id, text = boundary.sent[0]
    assert "Sumber:" not in text
    assert "tidak menemukan informasi" in text.lower()


def test_duplicate_update_is_answered_once(tmp_path: Path, synthetic_docs: Path):
    """AC-008 at mock level: redelivery of the same update sends once."""
    update = IncomingUpdate(3, "555", SUPPORTED_QUESTION)
    boundary = FakeBoundary([[update], [update]])
    poller = _poller(tmp_path, synthetic_docs, boundary, max_iterations=2)

    poller.run()

    assert len(boundary.sent) == 1


def test_mixed_batch_answers_only_the_valid_question(tmp_path: Path, synthetic_docs: Path):
    """A batch with a question, a command, and a non-text item is handled safely."""
    boundary = FakeBoundary(
        [
            [
                IncomingUpdate(10, "555", SUPPORTED_QUESTION),
                IncomingUpdate(11, "555", "/help"),
                IncomingUpdate(12, "555", None),
            ]
        ]
    )
    poller = _poller(tmp_path, synthetic_docs, boundary)

    poller.run()

    assert len(boundary.sent) == 3
    assert poller.counters.answers_delivered == 1
    assert poller.counters.rejected == 1
    assert poller._state.get_polling_offset() == 13
