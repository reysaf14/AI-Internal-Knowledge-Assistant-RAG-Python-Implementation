"""Decisive read-only test: can this bot receive updates *at all*?

Every other probe filtered by group id, which cannot distinguish "the group
message never arrived" from "no message of any kind ever arrived".  This one
removes the filter: it watches the raw queue and reports the **kind** of chat
each arriving update came from (private / group / supergroup / channel / other).

That single split decides the fix:

* **private arrives, group does not**  -> the bot is reachable and its queue
  works; the fault is group-specific (membership, privacy mode, or the operator
  typed into a different chat).
* **nothing arrives at all**  -> the fault is global (wrong token, a second
  consumer, or the operator messaged a different bot).

Read-only by construction: the offset is never advanced past ``0`` and the
result is never confirmed, so this probe cannot consume the operator's messages
and cannot steal traffic from a concurrently running poller.

Never prints the token, a full chat id, or message text -- only counts, a
trailing-4-digit chat suffix, and the chat kind.

Usage::

    python scripts/telegram_delivery_probe.py --seconds 150
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env


def _get_updates(token: str, timeout_s: int = 0) -> list[dict]:
    query = urllib.parse.urlencode(
        {"offset": 0, "limit": 100, "timeout": timeout_s, "allowed_updates": '["message"]'}
    )
    url = f"https://api.telegram.org/bot{token}/getUpdates?{query}"
    with urllib.request.urlopen(url, timeout=timeout_s + 20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("result") or []


def _kind(update: dict) -> tuple[str, str]:
    """Return ``(chat_kind, chat_id_suffix)`` for one raw update."""
    chat = ((update.get("message") or {}).get("chat")) or {}
    raw_id = str(chat.get("id", ""))
    suffix = raw_id[-4:] if raw_id else "----"
    return str(chat.get("type", "unknown")), suffix


def _bot_id(token: str) -> str:
    url = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("result") or {}
    return f"{result.get('first_name', '?')}|@{result.get('username', '?')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=150)
    parser.add_argument("--tick", type=int, default=6)
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    token = cfg.telegram_bot_token
    if not token:
        print("token_present=False")
        return 4

    print(f"bot_identity={_bot_id(token)}")
    print("ACTION=do BOTH, in any order:")
    print("  1. send one message in the GROUP")
    print("  2. send one message in a PRIVATE chat with the bot")
    print(f"watching_for_s={args.seconds} (read-only, offset never advanced)")

    kinds: dict[str, int] = {}
    chat_ids: dict[str, str] = {}
    total = 0
    deadline = time.perf_counter() + args.seconds
    next_beat = 0.0
    while time.perf_counter() < deadline:
        try:
            batch = _get_updates(token)
        except Exception as exc:  # noqa: BLE001 - a poll error must not end the probe
            print(f"poll_error={type(exc).__name__}", flush=True)
            time.sleep(args.tick)
            continue
        for update in batch:
            kind, suffix = _kind(update)
            key = f"{kind}:{suffix}"
            if key not in chat_ids:
                chat_ids[key] = str(update.get("update_id", ""))
                print(f"ARRIVED kind={kind} chat_suffix={suffix}", flush=True)
            kinds[kind] = kinds.get(kind, 0) + 1
        total = max(total, len(batch))
        if time.perf_counter() >= next_beat:
            remaining = max(0, int(deadline - time.perf_counter()))
            print(f"tick remaining_s={remaining} pending_now={len(batch)} seen={total}")
            next_beat = time.perf_counter() + 20.0
        time.sleep(args.tick)

    print("---- verdict ----")
    for kind in sorted(kinds):
        print(f"kind_{kind}={kinds[kind]}")
    private_seen = any(k in kinds for k in ("private",))
    group_seen = any(k in kinds for k in ("group", "supergroup"))
    if group_seen and private_seen:
        verdict = "BOTH_PATHS_ARRIVE"
    elif group_seen:
        verdict = "GROUP_ONLY_ARRIVES"
    elif private_seen:
        verdict = "PRIVATE_ONLY_ARRIVES__GROUP_FAULT"
    else:
        verdict = "NOTHING_ARRIVES__GLOBAL_FAULT"
    print(f"VERDICT={verdict}")
    print(f"pending_at_end={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
