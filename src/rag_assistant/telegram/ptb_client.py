"""python-telegram-bot implementation of the Telegram boundary.

The approved design names ``python-telegram-bot`` for long polling, update
parsing, and message sending. This adapter keeps the library for parsing and
sending, but drives its ``Bot`` API from the application's own bounded polling
loop instead of ``Application.run_polling()``, because AC-009/AC-010 require an
explicit single-instance guard, bounded backoff, bounded send retry, and an
observable send outcome -- none of which ``run_polling()`` exposes.

The library is asynchronous; each boundary call is executed with
``asyncio.run()``. That costs one HTTP client per call, which is negligible at
one call per long poll and keeps the rest of the application synchronous.

This module is intentionally **not** imported by ``rag_assistant.telegram`` so
the boundary, the loop, and the tests stay independent of the library and of any
network. Only the bot entry point imports it.
"""
from __future__ import annotations

import asyncio
import time

from telegram import Bot
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.error import TelegramError as PtbError

from rag_assistant.telegram.models import (
    IncomingUpdate,
    SendOutcome,
    SendResult,
    TelegramRateLimited,
    TelegramRejected,
    TelegramTimeout,
    TelegramUnavailable,
)
from rag_assistant.telegram.policy import (
    MAX_SEND_ATTEMPTS,
    POLL_READ_TIMEOUT_GRACE_SECONDS,
)

ALLOWED_UPDATES = ("message",)


def _retry_after_seconds(exc: RetryAfter) -> float:
    value = getattr(exc, "retry_after", 1)
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return float(value)


def _text_of(update: object) -> str | None:
    message = getattr(update, "effective_message", None)
    text = getattr(message, "text", None)
    return text if isinstance(text, str) else None


def _chat_id_of(update: object) -> str:
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    return "" if chat_id is None else str(chat_id)


class PtbTelegramClient:
    """Telegram boundary backed by ``python-telegram-bot``."""

    def __init__(
        self,
        *,
        token: str,
        poll_timeout_seconds: int = 30,
        request_timeout_seconds: int = 4,
        max_send_attempts: int = MAX_SEND_ATTEMPTS,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("token is required")
        self._token = token.strip()
        self._poll_timeout = poll_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._max_send_attempts = max(1, max_send_attempts)

    def get_updates(
        self, offset: int, timeout_seconds: int
    ) -> tuple[IncomingUpdate, ...]:
        """Long-poll Telegram and map updates to the local boundary type."""
        try:
            raw_updates = asyncio.run(self._fetch(offset, timeout_seconds))
        except TimedOut as exc:
            raise TelegramTimeout("long poll timed out") from exc
        except RetryAfter as exc:
            raise TelegramRateLimited(_retry_after_seconds(exc)) from exc
        except NetworkError as exc:
            raise TelegramUnavailable("telegram unreachable") from exc
        except PtbError as exc:
            raise TelegramUnavailable("telegram request failed") from exc

        return tuple(
            IncomingUpdate(
                update_id=item.update_id,
                chat_id=_chat_id_of(item),
                text=_text_of(item),
            )
            for item in raw_updates
        )

    def send_message(self, chat_id: str, text: str) -> SendResult:
        """Deliver one message, reporting a truthful outcome.

        Only a rate limit is retried (bounded). A timeout or transport failure
        is reported as ``UNKNOWN`` and never retried, because a second attempt
        could duplicate a message that already left the machine -- the design
        explicitly does not promise exactly-once delivery.
        """
        if not chat_id or not text:
            return SendResult(SendOutcome.FAILED, attempts=0, error_category="NO_TARGET")

        attempts = 0
        while True:
            attempts += 1
            try:
                asyncio.run(self._post(chat_id, text))
            except RetryAfter as exc:
                if attempts >= self._max_send_attempts:
                    return SendResult(
                        SendOutcome.FAILED, attempts, TelegramRateLimited.category
                    )
                time.sleep(_retry_after_seconds(exc))
                continue
            except TimedOut:
                return SendResult(
                    SendOutcome.UNKNOWN, attempts, TelegramTimeout.category
                )
            except NetworkError:
                return SendResult(
                    SendOutcome.UNKNOWN, attempts, TelegramUnavailable.category
                )
            except PtbError:
                return SendResult(
                    SendOutcome.FAILED, attempts, TelegramRejected.category
                )
            return SendResult(SendOutcome.SENT, attempts, "")

    async def _fetch(
        self, offset: int, timeout_seconds: int
    ) -> tuple[object, ...]:
        async with Bot(token=self._token) as bot:
            return await bot.get_updates(
                offset=offset,
                timeout=timeout_seconds,
                read_timeout=timeout_seconds + POLL_READ_TIMEOUT_GRACE_SECONDS,
                allowed_updates=list(ALLOWED_UPDATES),
            )

    async def _post(self, chat_id: str, text: str) -> object:
        async with Bot(token=self._token) as bot:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                read_timeout=self._request_timeout,
                write_timeout=self._request_timeout,
                connect_timeout=self._request_timeout,
            )
