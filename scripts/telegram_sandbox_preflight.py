"""Preflight check for the live Telegram sandbox (G3/G4).

Run this before the live sandbox run.  It answers one question: *is the local
setup complete enough to attempt it?*

It is strictly read-only and secret-safe:

* it calls ``getMe`` only -- never ``getUpdates``, never sends a message;
* it prints no token, no bot id, and no bot username, only coarse status, so
  the output is safe to paste into a report;
* token *shape* is validated before any network call, so a pasted-wrong value
  is reported as a shape error rather than a confusing 401.

Checks performed:

1. ``TELEGRAM_BOT_TOKEN`` (the application bot) is present and shaped like a
   Telegram bot token.
2. It authenticates against the live API (``getMe``).
3. Its ``can_read_all_group_messages`` flag is read from ``getMe`` itself, so
   privacy mode is reported as a fact instead of an honour-system reminder.

Why there is no second bot here
-------------------------------
An earlier revision required a "Bot B" to send the test questions.  That cannot
work.  Telegram's FAQ states that bots will not see messages from other bots,
regardless of mode, to prevent bot-to-bot loops -- confirmed live: Bot B sent
into the shared supergroup while Bot A's ``getUpdates`` stayed at zero, with
Bot A already a member, no webhook set, and privacy mode disabled.  The sender
must therefore be a **human**, so only the application bot is checked here.

One thing that still cannot be verified over the API: whether the operator has
actually joined the target group and typed into it.  That is what the live run
measures.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

from rag_assistant.config import load_config, load_operator_env

API_HOST = "api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10.0

BOT_A_VAR = "TELEGRAM_BOT_TOKEN"

# Telegram bot token: numeric bot id, a colon, then an opaque secret segment.
TOKEN_SHAPE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")

_ACCEPTED = "accepted"
_REJECTED = "rejected"
_UNREACHABLE = "unreachable"


def _sanitize(text: str) -> str:
    """Strip any token-shaped or bot-id-shaped fragment from a string."""
    text = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", text)
    return re.sub(r"\bbot\d{6,12}\b", "[REDACTED]", text)


def probe(token: str, get=None) -> tuple[str, dict[str, object]]:
    """Call ``getMe`` once and return ``(status, sanitized_fields)``.

    ``can_read_all_group_messages`` is the bot's own privacy-mode flag: ``True``
    means it receives every group message.  Reporting it turns the most common
    silent sandbox failure into a visible fact.
    """
    url = f"https://{API_HOST}/bot{token}/getMe"
    fetch = get or httpx.get
    try:
        response = fetch(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        return _UNREACHABLE, {"error_category": "TELEGRAM_TIMEOUT"}
    except httpx.HTTPError:
        return _UNREACHABLE, {"error_category": "TELEGRAM_UNREACHABLE"}

    if response.status_code == 401:
        return _REJECTED, {"error_category": "TELEGRAM_UNAUTHORIZED", "http_status": 401}
    if response.status_code == 429:
        return _REJECTED, {"error_category": "TELEGRAM_RATE_LIMITED", "http_status": 429}
    if response.status_code >= 400:
        return _REJECTED, {
            "error_category": "TELEGRAM_REQUEST_REJECTED",
            "http_status": response.status_code,
        }

    try:
        payload = response.json()
    except ValueError:
        return _REJECTED, {"error_category": "TELEGRAM_INVALID_RESPONSE"}

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return _REJECTED, {"error_category": "TELEGRAM_INVALID_RESPONSE"}

    # Only coarse capability flags; identity fields stay unread and unprinted.
    return _ACCEPTED, {
        "http_status": response.status_code,
        "is_bot": bool(result.get("is_bot", False)),
        "privacy_off": bool(result.get("can_read_all_group_messages", False)),
    }


def _read_env_file_value(root: Path, name: str) -> str:
    """Read one value straight from ``.env`` so presence is reported honestly.

    ``load_operator_env`` deliberately lets a process value win, which makes it
    impossible to tell "missing from .env" from "set in the shell".  Reading the
    file too lets the report name the exact place to fix.
    """
    env_file = root / ".env"
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            return value.strip()
    return ""


def _print_todo(missing_token: bool, shape_bad: bool) -> None:
    print("NEXT_STEPS")
    if missing_token:
        print(f"  1. Open .env and set the value of: {BOT_A_VAR}")
    if shape_bad:
        print("  ! The token does not look like 123456789:AA...")
        print("    Check for stray quotes or spaces around the value in .env.")
    print("  2. Add the bot to one Telegram group")
    print("  3. @BotFather -> /setprivacy -> select the bot -> Disable")
    print("     (privacy mode ON hides plain group messages from the bot)")
    print("  4. Send any message in that group")
    print("  5. Re-run: python scripts/telegram_sandbox_preflight.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing .env",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Check presence and shape only; skip the live getMe call",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    load_operator_env(root)
    load_config(root)  # fail fast on unrelated config problems

    token_a = os.environ.get(BOT_A_VAR, "").strip()
    file_a = _read_env_file_value(root, BOT_A_VAR)
    shape_ok = bool(TOKEN_SHAPE.match(token_a))

    print(f"bot_a_present={bool(token_a)} from_env_file={bool(file_a)}")
    print(f"bot_a_shape_ok={shape_ok}")

    if not token_a:
        print("verdict=NOT_READY")
        print("reason=bot_a_token_missing")
        _print_todo(missing_token=True, shape_bad=False)
        return 4

    if not shape_ok:
        print("verdict=NOT_READY")
        print("reason=token_shape_invalid")
        _print_todo(missing_token=False, shape_bad=True)
        return 4

    if args.no_network:
        print("verdict=READY_SHAPE_ONLY")
        print("scope=no-network")
        return 0

    status, fields = probe(token_a)
    print(f"bot_a_auth={status}")
    for key in ("is_bot", "privacy_off", "error_category"):
        if key in fields:
            print(f"bot_a_{key}={fields[key]}")
    if status != _ACCEPTED:
        print("verdict=NOT_READY")
        print("reason=telegram_auth_failed")
        return 1

    if not fields.get("privacy_off"):
        print("verdict=NOT_READY")
        print("reason=privacy_mode_still_enabled")
        print("FIX=@BotFather -> /setprivacy -> select the bot -> Disable")
        return 4

    print("verdict=READY")
    print("scope=presence-shape-auth-privacy")
    print("NEXT=python scripts/telegram_sandbox_e2e.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never let a raw traceback echo env values
        print("verdict=NOT_READY", file=sys.stderr)
        print("reason=unexpected_error", file=sys.stderr)
        raise SystemExit(1) from None
