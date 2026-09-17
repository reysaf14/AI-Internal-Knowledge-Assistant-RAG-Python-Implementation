"""Decisive read-only test: is anything *consuming* the bot's updates?

When a bot has ``privacy_off=True``, confirmed group membership, and an empty
``getUpdates`` queue, only three causes remain, and the earlier probes cannot
tell them apart:

* **A. never delivered** -- the message did not reach Telegram's queue for this
  bot at all (wrong chat, bot not in *that* chat, restriction);
* **B. consumed by someone else** -- another process (this machine, another
  machine, or a VPS) long-polls the same token and confirms the offset first;
* **C. restriction** -- the group forbids the bot from reading messages.

``getWebhookInfo.pending_update_count`` separates them.  That counter is
Telegram's own view of how many updates are waiting for *this* bot:

* it stays ``>0`` while nobody reads  -> **A is false; the message did arrive**;
* it flicks ``>0`` then back to ``0`` between our reads, while our own
  ``getUpdates`` sees nothing -> **B, a second consumer**;
* it stays ``0`` throughout          -> **A or C: nothing was ever queued**.

Output is counts and coarse flags only -- no token, no chat id, no message text.

Usage::

    python scripts/telegram_consumer_check.py --chat-id -100xxxxxxxxxx --seconds 240
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env


def _call(token: str, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    """One Bot API call.  The token only ever appears in the URL we build."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, default=0)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--round-timeout", type=int, default=8)
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    token = cfg.telegram_bot_token
    if not token:
        print("token_present=False")
        return 4

    info = (_call(token, "getWebhookInfo").get("result") or {})
    print(f"webhook_url_set={bool(info.get('url'))}")
    print(f"pending_at_start={info.get('pending_update_count', 0)}")

    if args.chat_id:
        member = _call(
            token,
            "getChatMember",
            {"chat_id": args.chat_id, "user_id": token.split(":", 1)[0]},
        )
        result = member.get("result") or {}
        print(f"bot_status={result.get('status', 'not_member')}")
        can_read = (result.get("can_read_messages") is not False)
        print(f"bot_can_read_messages={can_read}")

    high_water = 0
    seen_by_us = 0
    consumed_by_other = 0
    print(f"ACTION=send ONE message in the group now; watching {args.seconds}s")
    deadline = time.perf_counter() + args.seconds
    while time.perf_counter() < deadline:
        # Telegram's own counter: how much is queued for this bot.
        pending = (
            _call(token, "getWebhookInfo").get("result", {}).get("pending_update_count", 0)
        )
        high_water = max(high_water, pending)
        if pending > 0:
            # Drain with offset=0: read-only, does NOT confirm, so we can compare.
            batch = _call(
                token,
                "getUpdates",
                {"offset": 0, "limit": 100, "timeout": 0, "allowed_updates": '["message"]'},
            ).get("result", [])
            seen_by_us = max(seen_by_us, len(batch))
        elif high_water > 0 and seen_by_us == 0:
            # Went up and back to zero without us reading it.
            consumed_by_other += 1
        remaining = max(0, int(deadline - time.perf_counter()))
        print(
            f"tick remaining_s={remaining} pending={pending}"
            f" high_water={high_water} read_by_us={seen_by_us}"
            f" consumed_by_other_hits={consumed_by_other}",
            flush=True,
        )
        time.sleep(args.round_timeout)

    print("---- verdict ----")
    print(f"high_water_pending={high_water}")
    print(f"read_by_us={seen_by_us}")
    print(f"consumed_by_other_hits={consumed_by_other}")
    if seen_by_us > 0:
        verdict = "OPERATOR_MESSAGES_ARRIVED"
    elif consumed_by_other > 0:
        verdict = "SECOND_CONSUMER_POLLING_THE_TOKEN"
    else:
        verdict = "NOTHING_EVER_QUEUED"
    print(f"VERDICT={verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
