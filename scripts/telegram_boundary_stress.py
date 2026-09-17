"""Stress the real Telegram boundary in isolation, with no poller involved.

The live sandbox run answered exactly one question and then reported ``1/3``
for the rest of a 420 s window, even though the operator's later messages were
demonstrably present in the chat.  ``TelegramPoller`` counts an update as soon
as it arrives, so ``1/3`` means ``get_updates`` never handed over a second
batch -- either it kept returning empty, or it kept failing.

Those two causes need different fixes, and the poller's own counters cannot
separate them from the outside: ``poll_failures`` is reported only in the final
summary, which a cut-short window never reaches.  This script calls the real
boundary directly in a loop and prints the outcome of every single call, so the
distinction is visible immediately.

Read-only in the strict sense: the offset handed to Telegram is held constant.
A constant offset never confirms an update, so nothing is consumed and the
measured sandbox can still answer whatever is queued afterwards.

Never prints the token, a full chat id, or message content.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag_assistant.config import load_config, load_operator_env
from rag_assistant.telegram.ptb_client import PtbTelegramClient


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text.replace("\n", " ")[:220]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--poll-timeout", type=int, default=5)
    parser.add_argument(
        "--offset",
        type=int,
        default=-1,
        help="Offset to send; -1 reads the stored offset, 0 is always read-only",
    )
    args = parser.parse_args()

    load_operator_env(PROJECT_ROOT)
    cfg = load_config(PROJECT_ROOT)
    if not cfg.telegram_bot_token:
        print("token_present=False")
        return 4

    if args.offset >= 0:
        offset = args.offset
    else:
        from rag_assistant.storage.state_store import StateStore

        store = StateStore(PROJECT_ROOT / ".runtime" / "sandbox-e2e-state.sqlite3")
        offset = store.get_polling_offset()

    boundary = PtbTelegramClient(
        token=cfg.telegram_bot_token,
        poll_timeout_seconds=args.poll_timeout,
        request_timeout_seconds=cfg.telegram_request_timeout,
    )

    print(f"offset_used={offset} (constant; never confirms an update)")
    print(f"poll_timeout_s={args.poll_timeout} iterations={args.iterations}")

    ok_empty = ok_updates = failed = 0
    first_error = ""
    for i in range(1, args.iterations + 1):
        started = time.perf_counter()
        try:
            updates = boundary.get_updates(offset, args.poll_timeout)
        except BaseException as exc:  # noqa: BLE001 - classifying the failure IS the point
            failed += 1
            elapsed = time.perf_counter() - started
            print(f"[{i:03d}] FAIL t={elapsed:5.1f}s {_describe(exc)}", flush=True)
            if not first_error:
                first_error = _describe(exc)
            time.sleep(1)
            continue
        elapsed = time.perf_counter() - started
        if updates:
            ok_updates += 1
            ids = ",".join(str(u.update_id) for u in updates)
            print(f"[{i:03d}] UPDATES t={elapsed:5.1f}s n={len(updates)} ids={ids}", flush=True)
        else:
            ok_empty += 1
            print(f"[{i:03d}] empty t={elapsed:5.1f}s", flush=True)

    print("---- summary ----")
    print(f"ok_empty={ok_empty} ok_updates={ok_updates} failed={failed}")
    if first_error:
        print(f"FIRST_ERROR={first_error}")
    if failed == 0:
        print("VERDICT=BOUNDARY_HEALTHY (any missed update is a queue-side cause)")
    elif failed < args.iterations:
        print("VERDICT=BOUNDARY_INTERMITTENT")
    else:
        print("VERDICT=BOUNDARY_BROKEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
