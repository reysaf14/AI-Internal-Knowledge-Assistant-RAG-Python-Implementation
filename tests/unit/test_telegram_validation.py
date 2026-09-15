"""M4 unit tests: update validation runs before retrieval or any model call.

Covers AC-007 (invalid update rejected in a controlled way, without a model call
and without a sensitive retrieval, with at most one safe reply).
"""
from __future__ import annotations

import pytest

from rag_assistant.telegram.models import IncomingUpdate
from rag_assistant.telegram.policy import MAX_SAFE_REPLY_CHARS
from rag_assistant.telegram.validation import (
    HELP_TEXT,
    REPLY_EMPTY,
    REPLY_NON_TEXT,
    REPLY_TOO_LONG,
    REPLY_UNKNOWN_COMMAND,
    RejectionReason,
    UpdateKind,
    safe_reply_within_budget,
    validate_update,
)

MAX_CHARS = 2000


def _update(text: str | None, chat_id: str = "1", update_id: int = 10):
    return IncomingUpdate(update_id=update_id, chat_id=chat_id, text=text)


def test_text_question_is_accepted():
    """AC-006 input shape: a plain policy question becomes a question."""
    decision = validate_update(_update("Apa saja metode pembayaran?"), MAX_CHARS)

    assert decision.kind is UpdateKind.QUESTION
    assert decision.needs_retrieval
    assert decision.question == "Apa saja metode pembayaran?"
    assert decision.safe_reply == ""


def test_question_is_stripped_before_use():
    decision = validate_update(_update("   cuti tahunan berapa hari?   "), MAX_CHARS)

    assert decision.kind is UpdateKind.QUESTION
    assert decision.question == "cuti tahunan berapa hari?"


@pytest.mark.parametrize(
    ("text", "reason", "reply"),
    [
        ("", RejectionReason.EMPTY, REPLY_EMPTY),
        ("    ", RejectionReason.EMPTY, REPLY_EMPTY),
        (None, RejectionReason.NON_TEXT, REPLY_NON_TEXT),
        ("/unknown", RejectionReason.UNKNOWN_COMMAND, REPLY_UNKNOWN_COMMAND),
        ("x" * 2001, RejectionReason.TOO_LONG, REPLY_TOO_LONG),
    ],
    ids=["empty", "whitespace", "non-text", "unknown-command", "too-long"],
)
def test_invalid_updates_are_rejected_with_one_safe_reply(text, reason, reply):
    """AC-007: each invalid shape is rejected with exactly one safe reply."""
    decision = validate_update(_update(text), MAX_CHARS)

    assert decision.kind is UpdateKind.REJECTED
    assert decision.reason is reason
    assert decision.safe_reply == reply
    assert not decision.needs_retrieval
    assert decision.question == ""


def test_question_at_exact_limit_is_accepted():
    """The length limit is inclusive: only longer input is refused."""
    decision = validate_update(_update("x" * MAX_CHARS), MAX_CHARS)

    assert decision.kind is UpdateKind.QUESTION


def test_help_commands_are_answered_without_retrieval():
    """Commands are handled locally and never read the corpus."""
    for command in ("/help", "/start", "/start@SomeBot", "/HELP"):
        decision = validate_update(_update(command), MAX_CHARS)

        assert decision.kind is UpdateKind.HELP, command
        assert decision.safe_reply == HELP_TEXT
        assert not decision.needs_retrieval


def test_missing_chat_is_rejected_without_any_reply():
    """No chat means there is nowhere safe to reply, so nothing is sent."""
    decision = validate_update(_update("pertanyaan", chat_id=""), MAX_CHARS)

    assert decision.kind is UpdateKind.REJECTED
    assert decision.reason is RejectionReason.NO_CHAT
    assert decision.safe_reply == ""


def test_all_canned_replies_respect_the_locked_budget():
    """No canned reply may exceed the locked reply budget."""
    replies = [HELP_TEXT, REPLY_EMPTY, REPLY_NON_TEXT, REPLY_TOO_LONG, REPLY_UNKNOWN_COMMAND]

    for reply in replies:
        assert safe_reply_within_budget(reply)
        assert len(reply) <= MAX_SAFE_REPLY_CHARS


def test_decision_repr_does_not_expose_the_question():
    """A logged decision must not be able to leak the user's message."""
    secret = "RAHASIA-PERTANYAAN-1234"

    decision = validate_update(_update(secret), MAX_CHARS)

    assert secret in decision.question
    assert secret not in repr(decision)
