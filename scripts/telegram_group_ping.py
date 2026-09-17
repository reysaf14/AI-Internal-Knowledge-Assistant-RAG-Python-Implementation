"""Read-only + one-shot ping: prove the bot can be seen and heard in the group.

Two facts matter and both are checkable in one call each:

1. ``getChat`` on the target id -- does this id still resolve, and what kind of
   chat is it?  If the user has been typing somewhere else, this is where that
   shows up.
2. ``sendMessage`` into that chat -- can the bot *post*?  A successful post
   proves the bot is present in that exact chat and gives the operator a
   concrete message to reply to, which removes every ambiguity about *which*
   chat to type in.

The ping text is fixed and harmless.  Never prints the token or a full chat id.

Usage::

    python scripts/telegram_group_ping.py --chat-id -100xxxxxxxxxx
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

PING_TEXT = "Ping uji koneksi. Balas pesan ini dengan pertanyaan uji."


def _call(token: str, method: str, params: dict | None = None) -> tuple[int, dict]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(url, data=data, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, {"raw": body[:300]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--no-send", action="store_true", help="Only inspect, do not post")
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    token = cfg.telegram_bot_token
    if not token:
        print("token_present=False")
        return 4

    status, payload = _call(token, "getMe")
    me = payload.get("result") or {}
    print(f"bot=@{me.get('username', '?')} id={me.get('id', '?')}")
    print(f"target_chat_id_suffix={str(args.chat_id)[-4:]}")

    status, payload = _call(token, "getChat", {"chat_id": args.chat_id})
    print(f"getChat_http={status} ok={payload.get('ok')}")
    chat = payload.get("result") or {}
    if chat:
        print(f"chat_type={chat.get('type')} chat_title={chat.get('title', '')!r}")
        print(f"chat_username=@{chat.get('username', '')}" if chat.get("username") else "")
    else:
        print(f"getChat_error={payload.get('description', payload.get('raw', ''))}")

    status, payload = _call(
        token, "getChatMember", {"chat_id": args.chat_id, "user_id": me.get("id")}
    )
    member = payload.get("result") or {}
    print(f"bot_status={member.get('status', 'unknown')}")

    if args.no_send:
        return 0

    status, payload = _call(
        token, "sendMessage", {"chat_id": args.chat_id, "text": PING_TEXT}
    )
    ok = bool(payload.get("ok"))
    print(f"sendMessage_http={status} ok={ok}")
    if ok:
        message_id = (payload.get("result") or {}).get("message_id")
        print(f"ping_message_id={message_id}")
        print("VERDICT=BOT_CAN_POST_IN_THIS_CHAT")
        print("ACTION=reply to that ping message with one test question")
    else:
        print(f"sendMessage_error={payload.get('description', payload.get('raw', ''))}")
        print("VERDICT=BOT_CANNOT_POST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
