"""Force one inbound update from the target group, with no human in the loop.

Why this exists
---------------
Four live runs failed to receive a single group message, and each time the
operator reported having sent one.  Reading the queue directly settled it: the
arrival was a *private* message (chat id ending 1856) while the run was aimed at
the group (ending 7574).  Telegram delivered it to the same bot, the pipeline
answered it, and the run looked like "1 of 3 answered" instead of "wrong chat".

That leaves one question the queue cannot answer: **will a message typed in the
group ever be delivered?**  Waiting on a human to test that is slow and, in
practice, unreliable -- so this script makes the bot itself produce an inbound
group update, using a *reply to the bot's own message*.

Mechanism: ``sendMessage`` posts a prompt into the group, then the operator
replies to it.  A reply is still a human message (a bot's own message is never
delivered back to itself), so a human is still required for the reply -- but the
prompt makes the intended target unambiguous and gives the operator something
concrete to reply *to*, inside the group, on the record.  The script then
watches the group's queue with the offset pinned at 0, so nothing is consumed
and the measured run can still answer the reply afterwards.

Read-only with respect to the queue (offset constant at 0).
Never prints the token, a full chat id, or message content.
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
from rag_assistant.telegram.ptb_client import PtbTelegramClient

PROMPT_TEXT = (
    "Uji koneksi: balas pesan INI dengan pertanyaan "
    "'Jam berapa toko Makmur Jaya tutup?'"
)


def _call(token: str, method: str, params: dict | None = None) -> tuple[int, dict]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(url, data=data, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"raw": exc.read().decode("utf-8", "replace")[:300]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--poll-timeout", type=int, default=5)
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    token = cfg.telegram_bot_token
    if not token:
        print("token_present=False")
        return 4

    status, payload = _call(token, "getChat", {"chat_id": args.chat_id})
    chat = (payload or {}).get("result") or {}
    print(f"getChat http={status} ok={payload.get('ok')}")
    print(f" title={chat.get('title')!r} type={chat.get('type')}")
    print(f" target_suffix={str(args.chat_id)[-4:]}")
    if status != 200:
        return 4

    message_id = 0
    if not args.no_send:
        status, payload = _call(
            token, "sendMessage", {"chat_id": args.chat_id, "text": PROMPT_TEXT}
        )
        message_id = ((payload or {}).get("result") or {}).get("message_id", 0)
        print(f"sendMessage http={status} ok={payload.get('ok')} message_id={message_id}")
        if status != 200:
            return 4
        print("NOW=reply to that exact message inside the GROUP (swipe on it)")

    boundary = PtbTelegramClient(
        token=token,
        poll_timeout_seconds=args.poll_timeout,
        request_timeout_seconds=cfg.telegram_request_timeout,
    )
    print("mode=READ_ONLY (offset pinned at 0; nothing is consumed)")
    deadline = time.perf_counter() + args.seconds
    seen: dict[int, str] = {}
    polls = failures = 0
    while time.perf_counter() < deadline:
        polls += 1
        try:
            updates = boundary.get_updates(0, args.poll_timeout)
        except BaseException as exc:  # noqa: BLE001 - classification is the point
            failures += 1
            print(f"[{time.strftime('%H:%M:%S')}] FAIL {type(exc).__name__}", flush=True)
            time.sleep(1)
            continue
        for update in updates:
            seen[update.update_id] = update.chat_id or "none"
            suffix = (update.chat_id or "")[-4:]
            on_target = (update.chat_id or "") == str(args.chat_id)
            print(
                f"[{time.strftime('%H:%M:%S')}] UPDATE id={update.update_id}"
                f" chat_suffix={suffix} on_target={on_target}"
                f" text_len={len(getattr(update, 'text', '') or '')}",
                flush=True,
            )
        if polls % 4 == 0 and not seen:
            print(
                f"[{time.strftime('%H:%M:%S')}] waiting polls={polls}"
                f" updates=0 failures={failures}",
                flush=True,
            )

    print("---- summary ----")
    print(f"polls={polls} failures={failures} distinct_updates={len(seen)}")
    on_target = [u for u, c in seen.items() if c == str(args.chat_id)]
    off_target = [u for u, c in seen.items() if c != str(args.chat_id)]
    print(f"on_target={len(on_target)} off_target={len(off_target)}")
    if on_target:
        print("VERDICT=GROUP_DELIVERY_CONFIRMED")
    elif off_target:
        print("VERDICT=MESSAGES_ARRIVED_FROM_ANOTHER_CHAT (not the group)")
    else:
        print("VERDICT=NO_UPDATE_ARRIVED_IN_WINDOW")
    print("note=read-only; nothing consumed; queued updates remain available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
