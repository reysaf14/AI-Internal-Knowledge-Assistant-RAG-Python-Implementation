"""Telegram polling boundary.

Deliberately does **not** import ``ptb_client``: the boundary types, the
validation rules, the single-instance lock, and the polling loop must stay
importable (and testable) without the Telegram library or any network access.
The bot entry point imports ``rag_assistant.telegram.ptb_client`` explicitly.
"""

from rag_assistant.telegram.lock import InstanceLockError, SingleInstanceLock
from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
    TelegramBoundary,
    TelegramError,
    TelegramRateLimited,
    TelegramRejected,
    TelegramTimeout,
    TelegramUnavailable,
)
from rag_assistant.telegram.poller import PollCounters, TelegramPoller
from rag_assistant.telegram.validation import (
    RejectionReason,
    UpdateKind,
    ValidationDecision,
    validate_update,
)

__all__ = [
    "IncomingUpdate",
    "InstanceLockError",
    "PollCounters",
    "RejectionReason",
    "SendOutcome",
    "SendResult",
    "SingleInstanceLock",
    "TelegramBoundary",
    "TelegramError",
    "TelegramPoller",
    "TelegramRateLimited",
    "TelegramRejected",
    "TelegramTimeout",
    "TelegramUnavailable",
    "UpdateKind",
    "ValidationDecision",
    "validate_update",
]
