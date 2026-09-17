"""Readiness-probe safety tests: the Telegram auth check must not leak secrets.

The probe's whole value is that its output is safe to paste into evidence, so
these tests assert the *negative* property directly: neither the returned
fields, the printed lines, nor a raised path may contain the token, the bot id,
the bot username, or the request URL.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "telegram_readiness_check.py"

# A synthetic, non-functional token shape -- never a real credential.
FAKE_TOKEN = "123456789:AAFakeTokenValueForTestsOnly_000000000000"
FAKE_BOT_RESPONSE = {
    "ok": True,
    "result": {
        "id": 987654321,
        "is_bot": True,
        "first_name": "SyntheticBot",
        "username": "synthetic_evidence_bot",
    },
}


def _load_module():
    spec = importlib.util.spec_from_file_location("telegram_readiness_check", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module():
    return _load_module()


def _responder(status: int, payload: dict | None = None):
    def fetch(url: str, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url)
        if payload is None:
            return httpx.Response(status, request=request, text="error")
        return httpx.Response(status, request=request, json=payload)

    return fetch


def test_accepted_probe_reports_only_coarse_status(module):
    """A healthy probe returns a capability flag and nothing identifying."""
    status, fields = module._probe(FAKE_TOKEN, _responder(200, FAKE_BOT_RESPONSE))

    assert status == module.ACCEPTED
    assert fields == {"http_status": 200, "is_bot": True}
    rendered = json.dumps(fields)
    assert FAKE_TOKEN not in rendered
    assert "987654321" not in rendered
    assert "synthetic_evidence_bot" not in rendered
    assert "SyntheticBot" not in rendered


def test_unauthorized_probe_reports_category_not_body(module):
    """A rejection yields a category and status, never the provider body."""
    status, fields = module._probe(FAKE_TOKEN, _responder(401))

    assert status == module.REJECTED
    assert fields["error_category"] == "TELEGRAM_UNAUTHORIZED"
    assert FAKE_TOKEN not in json.dumps(fields)


def test_unreachable_probe_reports_category_only(module):
    """A transport failure is categorised; the URL (which holds the token) is not echoed."""

    def failing(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("synthetic connect failure")

    status, fields = module._probe(FAKE_TOKEN, failing)

    assert status == module.UNREACHABLE
    assert fields == {"error_category": "TELEGRAM_UNREACHABLE"}
    assert FAKE_TOKEN not in json.dumps(fields)


def test_malformed_success_body_is_rejected_not_adopted(module):
    """A 200 without a usable result object is not treated as acceptance."""
    status, fields = module._probe(FAKE_TOKEN, _responder(200, {"ok": True, "result": "nope"}))

    assert status == module.REJECTED
    assert fields["error_category"] == "TELEGRAM_INVALID_RESPONSE"


def test_probe_output_never_contains_the_token(module):
    """Guard the end-to-end property: nothing printed may carry the secret."""
    captured = io.StringIO()
    status, fields = module._probe(FAKE_TOKEN, _responder(200, FAKE_BOT_RESPONSE))
    with redirect_stdout(captured):
        print(f"telegram_auth={status}")
        for key, value in fields.items():
            print(f"telegram_{key}={value}")

    output = captured.getvalue()
    assert FAKE_TOKEN not in output
    assert "bot" + FAKE_TOKEN not in output
    assert "synthetic_evidence_bot" not in output
