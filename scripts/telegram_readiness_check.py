"""Read-only Telegram authentication and connectivity smoke check.

This closes the *authentication* half of the M4/M5 Telegram gap without
touching the sandbox polling path:

* it calls ``getMe`` only -- it never fetches updates, never sends a message,
  and never acknowledges an update;
* it prints no token, no bot id, no bot username, and no chat identity -- only
  a coarse status, so the output is safe to paste into evidence;
* a failing result is reported with a category, never with a raw provider body
  or URL (the token lives in the request URL, so exception text is never
  echoed).

What it does **not** prove: sandbox delivery, duplicate redelivery timing, or
end-to-end latency. Those still require the full sandbox run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from rag_assistant.config import load_config, load_operator_env, validate_runtime_config

ACCEPTED = "accepted"
REJECTED = "rejected"
UNREACHABLE = "unreachable"

# Bounded, single attempt: a readiness probe must not retry or hang.
REQUEST_TIMEOUT_SECONDS = 10.0

API_HOST = "api.telegram.org"


def _probe(token: str, get=None) -> tuple[str, dict[str, object]]:
    """Call ``getMe`` once and return ``(status, sanitized_fields)``."""
    url = f"https://{API_HOST}/bot{token}/getMe"
    fetch = get or httpx.get
    try:
        response = fetch(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        return UNREACHABLE, {"error_category": "TELEGRAM_TIMEOUT"}
    except httpx.HTTPError:
        return UNREACHABLE, {"error_category": "TELEGRAM_UNREACHABLE"}

    if response.status_code == 401:
        return REJECTED, {"error_category": "TELEGRAM_UNAUTHORIZED", "http_status": 401}
    if response.status_code == 429:
        return REJECTED, {"error_category": "TELEGRAM_RATE_LIMITED", "http_status": 429}
    if response.status_code >= 400:
        return REJECTED, {
            "error_category": "TELEGRAM_REQUEST_REJECTED",
            "http_status": response.status_code,
        }

    try:
        payload = response.json()
    except ValueError:
        return REJECTED, {"error_category": "TELEGRAM_INVALID_RESPONSE"}

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return REJECTED, {"error_category": "TELEGRAM_INVALID_RESPONSE"}

    # Only a coarse capability flag; identity fields stay unread and unprinted.
    return ACCEPTED, {
        "http_status": response.status_code,
        "is_bot": bool(result.get("is_bot", False)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing .env (default: current directory)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    load_operator_env(project_root)
    cfg = load_config(project_root)
    # Reuse the production readiness gate so this probe cannot pass while the
    # bot runtime itself would refuse to start.
    validate_runtime_config(cfg, "bot")

    parsed = urlparse(cfg.llm_base_url)
    print(f"llm_host={parsed.hostname or 'unset'}")
    print(f"llm_port={parsed.port if parsed.port is not None else 'default'}")

    status, fields = _probe(cfg.telegram_bot_token)
    print(f"telegram_auth={status}")
    for key in ("http_status", "is_bot", "error_category"):
        if key in fields:
            print(f"telegram_{key}={fields[key]}")

    if status == ACCEPTED:
        print("scope=authentication-and-connectivity-only")
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never let a raw traceback echo env values
        print("telegram_auth=error", file=sys.stderr)
        raise SystemExit(1) from None
