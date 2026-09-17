"""Watch the Telegram inbound queue in read-only mode, one poll at a time.

Purpose: answer one question with evidence -- *is a message the operator typed
into the group actually queued for this bot at all?*

Why this exists
---------------
A live E2E window answered one question and then reported ``1/3`` for three
straight minutes while the operator's next two messages were demonstrably
visible in the group.  The poller's own counters cannot separate the two causes:

* Telegram never queued the messages (loss happens before delivery), or
* Telegram queued them but this consumer never saw them (offset/consumer fault).

``getUpdates`` alone cannot tell them apart either, because a *consumed* update
and a *never-queued* update both show up as nothing.  Two things make the
distinction observable here:

* ``getWebhookInfo.pending_update_count`` reports how many updates Telegram is
  holding, and unlike ``getUpdates`` it consumes nothing.
* The offset is pinned at ``0``.  An offset never confirms an update, so nothing
  is ever removed from the queue -- the measured sandbox can still answer
  whatever the operator sent after this script exits.

Read-only in the strict sense: this script cannot consume an update even if it
wants to.  Never prints the token, a full chat id, or message content -- only
lengths and coarse chat type.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.telegram.ptb_client import PtbTelegramClient


def _pending(token: str) -> object:
    try:
        response = httpx.get(
            f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15.0
        )
        return (response.json().get("result") or {}).get("pending_update_count", "?")
    except (httpx.HTTPError, ValueError):
        return "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--poll-timeout", type=int, default=5)
    parser.add_argument("--chat-id", type=int, default=0, help="Only report this chat")
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    if not cfg.telegram_bot_token:
        print("token_present=False")
        return 4

    boundary = PtbTelegramClient(
        token=cfg.telegram_bot_token,
        poll_timeout_seconds=args.poll_timeout,
        request_timeout_seconds=cfg.telegram_request_timeout,
    )
    try:
        me = httpx.get(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/getMe", timeout=15.0
        ).json()["result"]
    except (httpx.HTTPError, ValueError, KeyError):
        print("identity=unavailable")
        return 4

    print(f"bot_id={me.get('id')} username={me.get('username')}")
    print(f"group_ids_are_negative=True target_chat={args.chat_id or 'any'}")
    print("mode=READ_ONLY (offset pinned at 0; nothing can be consumed)")
    print(f"window_s={args.seconds} poll_timeout_s={args.poll_timeout}")

    deadline = time.perf_counter() + args.seconds
    seen_total = 0
    polls = 0
    failures = 0
    while time.perf_counter() < deadline:
        polls += 1
        started = time.perf_counter()
        try:
            updates = boundary.get_updates(0, args.poll_timeout)
        except BaseException as exc:  # noqa: BLE001 - classification is the point
            failures += 1
            print(f"[{time.strftime('%H:%M:%S')}] FAIL {type(exc).__name__}", flush=True)
            time.sleep(1)
            continue
        elapsed = time.perf_counter() - started
        pending = _pending(cfg.telegram_bot_token)
        if updates:
            seen_total += len(updates)
            for update in updates:
                suffix = (update.chat_id or "")[-4:]
                print(
                    f"[{time.strftime('%H:%M:%S')}] UPDATE id={update.update_id}"
                    f" chat_suffix={suffix or 'none'}"
                    f" text_len={len(getattr(update, 'text', '') or '')}"
                    f" poll_t={elapsed:.1f}s pending_at_telegram={pending}",
                    flush=True,
                )
        else:
            if polls % 3 == 0:
                print(
                    f"[{time.strftime('%H:%M:%S')}] empty poll_t={elapsed:.1f}s"
                    f" pending_at_telegram={pending} polls={polls}",
                    flush=True,
                )

    print("---- summary ----")
    print(f"polls={polls} failures={failures} updates_seen={seen_total}")
    if seen_total:
        print("VERDICT=DELIVERED (Telegram does queue this chat's messages)")
    else:
        print("VERDICT=NOTHING_QUEUED_AT_ANY_POINT_IN_WINDOW")
    print("note=read-only; nothing consumed; the queued message is still available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
