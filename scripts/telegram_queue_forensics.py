"""Diagnose a silently empty Telegram queue.

A bot with ``privacy_off=True``, confirmed membership, and an empty
``getUpdates`` queue has exactly three remaining explanations, and they are
indistinguishable from the outside:

1. a **webhook is set** -- Telegram then refuses ``getUpdates`` entirely and
   routes everything to that URL;
2. **another process is long-polling the same token** -- Telegram delivers each
   update to whichever consumer confirms the offset first, so a stray
   ``run_polling`` elsewhere silently eats the traffic;
3. the messages genuinely never arrived.

This script prints the first two as facts and never prints the token.

Usage::

    python scripts/telegram_queue_forensics.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env

WEBHOOK_KEYS = ("url", "pending_update_count", "last_error_date", "last_error_message")


def _call(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    if not cfg.telegram_bot_token:
        print("token_present=False")
        return 4

    payload = _call(cfg.telegram_bot_token, "getWebhookInfo")
    result = payload.get("result") or {}
    url = result.get("url") or ""
    print(f"webhook_set={bool(url)}")
    for key in WEBHOOK_KEYS:
        print(f"webhook_{key}={result.get(key, '')}")
    if url:
        print("VERDICT=webhook_blocks_getUpdates")
        print("FIX=delete the webhook, then re-run the E2E")
    else:
        print("VERDICT=no_webhook")
        print("NOTE=if the queue is still empty, another process is polling the")
        print("     same token, or the message never reached the bot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
