"""Read-only probe: what is sitting in the bot's update queue right now?

Answers three questions the E2E script cannot answer mid-failure:

1. is the queue empty (the operator's message never arrived), or
2. is it holding the operator's questions (the E2E loop died before reading
   them), and
3. in the first case, was the message delivered to a *private* chat instead of
   the group -- the single most common operator mistake, and one that produces
   exactly the same "zero updates in the group" symptom?

Strictly read-only: ``getUpdates`` is called with ``offset=0``, which never
confirms and never drops an update.  Nothing is sent.  Output is counts, chat
kinds, and text lengths only -- no token, no chat id, no message body.

With ``--watch-seconds`` the same read-only poll repeats, so the operator can
send a message *while it runs* and watch it land in real time.  That is the only
way to separate "your message never reached the bot" from "the bot read it and
something later ate it".

Usage::

    python scripts/telegram_probe_queue.py
    python scripts/telegram_probe_queue.py --chat-id -100xxxxxxxxxx
    python scripts/telegram_probe_queue.py --watch-seconds 120
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from telegram import Bot

from rag_assistant.config import load_config, load_operator_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_HOST = "api.telegram.org"


def _bot_id(token: str) -> str:
    """The numeric bot id is the part before the colon; never printed."""
    return token.split(":", 1)[0].strip()


async def _fetch(token: str, timeout_seconds: int) -> tuple[object, ...]:
    async with Bot(token=token) as bot:
        return await bot.get_updates(
            offset=0,
            timeout=timeout_seconds,
            read_timeout=timeout_seconds + 5,
            allowed_updates=["message"],
        )


def _membership(token: str, chat_id: int) -> str:
    """Report whether the bot is still a member, using ``getChatMember``.

    A bot that was added and later removed looks identical to a privacy-mode
    block from the outside.  This call distinguishes them, and prints only the
    coarse status word.
    """
    import httpx

    url = f"https://{API_HOST}/bot{token}/getChatMember"
    try:
        response = httpx.get(
            url,
            params={"chat_id": chat_id, "user_id": _bot_id(token)},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return f"unreachable({type(exc).__name__})"
    try:
        payload = response.json()
    except ValueError:
        return f"invalid_response({response.status_code})"
    if not payload.get("ok"):
        # error_code 400 + "user not found" means the bot is not a member.
        return f"not_member({payload.get('error_code', response.status_code)})"
    result = payload.get("result") or {}
    return str(result.get("status", "unknown"))


def _describe(item: object) -> str:
    chat = getattr(item, "effective_chat", None)
    chat_id = getattr(chat, "id", 0) or 0
    kind = "group" if chat_id < 0 else "private"
    text = getattr(getattr(item, "effective_message", None), "text", None)
    return (
        f"  update_id={item.update_id} chat_kind={kind}"
        f" text_chars={len(text) if isinstance(text, str) else 0}"
    )


def _one_round(token: str, timeout_seconds: int) -> tuple[object, ...]:
    try:
        return asyncio.run(_fetch(token, timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - category only, never the message
        print(f"error_category={type(exc).__name__}")
        return ()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chat-id",
        type=int,
        default=0,
        help="Also report the bot's membership status in this chat",
    )
    parser.add_argument(
        "--watch-seconds",
        type=int,
        default=0,
        help="Keep polling read-only for this long (0 = single look)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=3,
        help="Per-round long-poll timeout in seconds",
    )
    args = parser.parse_args()

    root = PROJECT_ROOT
    load_operator_env(root)
    cfg = load_config(root)
    if not cfg.telegram_bot_token:
        print("token_present=False")
        return 4

    if args.chat_id:
        print(f"bot_membership={_membership(cfg.telegram_bot_token, args.chat_id)}")

    if args.watch_seconds <= 0:
        updates = _one_round(cfg.telegram_bot_token, args.poll_timeout)
        print(f"pending_updates={len(updates)}")
        for item in updates:
            print(_describe(item))
        if not updates:
            print("NOTE=queue is empty; a consumed offset or an undelivered message")
            print("NOTE=if you typed in a group and this is still 0, the bot is not")
            print("     receiving group messages -- check membership and privacy mode")
        return 0

    deadline = time.perf_counter() + args.watch_seconds
    seen = 0
    print(f"watching_for_s={args.watch_seconds}")
    print("ACTION=send your message in the group now")
    while time.perf_counter() < deadline:
        updates = _one_round(cfg.telegram_bot_token, args.poll_timeout)
        for item in updates:
            seen += 1
            print(_describe(item), flush=True)
        remaining = max(0, int(deadline - time.perf_counter()))
        print(f"tick remaining_s={remaining} total_seen={seen}", flush=True)
    print(json.dumps({"total_seen": seen, "watch_seconds": args.watch_seconds}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
