"""Decisive read-only test for a *second consumer* of the same bot token.

Telegram hands each update to exactly one consumer, and permits only one
``getUpdates`` long-poll (or one webhook) at a time.  A stray consumer therefore
produces a very specific signature that no sampling-based probe can see:

    HTTP 409  Conflict: terminated by other getUpdates request

Crucially, ``pending_update_count`` stays at ``0`` the whole time in that
scenario -- the other consumer confirms each offset within milliseconds, so the
queue never *looks* full.  That is why the earlier probes reported
"nothing ever queued" and could not distinguish it from a genuine delivery
fault.  The 409 is the only reliable tell.

This script issues one long poll and reports which of these it is:

* **409**                  -> a second consumer (or webhook) owns the token
* **200 with updates**     -> we are the only consumer and traffic is arriving
* **200 with no updates**  -> we are the only consumer and nothing was sent

Read-only: offset stays ``0``, so no update is confirmed and none is consumed.

Never prints the token, a full chat id, or message text.

Usage::

    python scripts/telegram_conflict_probe.py --timeout 30
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env


def _bot_identity(token: str) -> str:
    url = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8")).get("result") or {}
    return f"{result.get('first_name', '?')}|@{result.get('username', '?')}|id={result.get('id', '?')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=30, help="Long-poll seconds")
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    token = cfg.telegram_bot_token
    if not token:
        print("token_present=False")
        return 4

    print(f"bot_identity={_bot_identity(token)}")

    query = urllib.parse.urlencode(
        {"offset": 0, "limit": 10, "timeout": args.timeout, "allowed_updates": '["message"]'}
    )
    url = f"https://api.telegram.org/bot{token}/getUpdates?{query}"
    print(f"issuing long poll (timeout={args.timeout}s) ...")
    try:
        with urllib.request.urlopen(url, timeout=args.timeout + 25) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = payload.get("result") or []
        print(f"http_status=200 updates_in_queue={len(result)}")
        for update in result[:5]:
            chat = ((update.get("message") or {}).get("chat")) or {}
            text_len = len(((update.get("message") or {}).get("text")) or "")
            print(
                f"  update kind={chat.get('type', '?')}"
                f" chat_suffix={str(chat.get('id', ''))[-4:]} text_chars={text_len}"
            )
        if result:
            print("VERDICT=SOLE_CONSUMER_TRAFFIC_PRESENT")
        else:
            print("VERDICT=SOLE_CONSUMER_QUEUE_EMPTY")
            print("NOTE=we hold the only long poll, so nothing is stealing updates;")
            print("     the messages genuinely are not reaching this bot")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"http_status={exc.code}")
        print(f"error_body={body[:300]}")
        if exc.code == 409:
            print("VERDICT=SECOND_CONSUMER_OWNS_THE_TOKEN")
            print("FIX=stop the other poller (another machine, a systemd service, or")
            print("    a leftover background process), then re-run the E2E")
        else:
            print("VERDICT=UNEXPECTED_HTTP_ERROR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
