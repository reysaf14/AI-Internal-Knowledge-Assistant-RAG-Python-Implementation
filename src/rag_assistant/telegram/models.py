"""Telegram boundary types: updates, send results, errors, and the client protocol.

Message content and chat identity are marked ``repr=False`` on purpose: an
accidental ``repr()`` in a log line or a traceback must not be able to leak
them, because the design stores and logs only technical metadata.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class TelegramError(Exception):
    """Controlled Telegram boundary failure; never carries a payload."""

    category = "TELEGRAM_ERROR"


class TelegramTimeout(TelegramError):
    """A Telegram request exceeded its timeout."""

    category = "TELEGRAM_TIMEOUT"


class TelegramUnavailable(TelegramError):
    """Telegram was unreachable or returned a transport-level error."""

    category = "TELEGRAM_UNAVAILABLE"


class TelegramRateLimited(TelegramError):
    """Telegram asked the client to slow down."""

    category = "TELEGRAM_RATE_LIMITED"

    def __init__(self, retry_after_seconds: float = 1.0) -> None:
        super().__init__("telegram rate limited")
        self.retry_after_seconds = float(retry_after_seconds)


class TelegramRejected(TelegramError):
    """Telegram definitively refused the request; retrying cannot help."""

    category = "TELEGRAM_REJECTED"


@dataclass(frozen=True)
class IncomingUpdate:
    """One inbound update with the minimum data needed to answer it.

    ``chat_id`` and ``text`` are excluded from ``repr`` deliberately. They are
    held transiently in memory only and must never be persisted or logged.
    """

    update_id: int
    chat_id: str = field(repr=False)
    text: str | None = field(repr=False)


class SendOutcome(Enum):
    """Truthful outcome of one outbound send."""

    SENT = "sent"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class SendResult:
    """Result of an outbound send. Carries no message content or chat id."""

    outcome: SendOutcome
    attempts: int = 1
    error_category: str = ""

    @property
    def is_success(self) -> bool:
        """Only a confirmed delivery counts as success."""
        return self.outcome is SendOutcome.SENT


class TelegramBoundary(Protocol):
    """The only Telegram surface the polling loop depends on.

    Unit and mock integration tests implement this protocol with a local fake,
    so no test needs a token, a network, or a Telegram account.
    """

    def get_updates(
        self, offset: int, timeout_seconds: int
    ) -> Sequence[IncomingUpdate]:
        """Fetch updates whose id is at least ``offset``."""
        ...

    def send_message(self, chat_id: str, text: str) -> SendResult:
        """Deliver one message and report a truthful outcome."""
        ...
