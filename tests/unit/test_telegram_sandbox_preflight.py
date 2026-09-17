"""Sandbox-preflight safety tests.

The preflight's output goes straight into the G3/G4 evidence, so its secret
safety is a contract, not a nicety.  These tests assert the negative property
directly: no returned field, printed line, or branch may carry a token, a bot
id, or a bot username.

The other half of the contract is *honesty*.  Two facts must be reported rather
than assumed:

* a missing or mis-shaped token is NOT_READY, never a silent pass;
* privacy mode is read from ``getMe``'s ``can_read_all_group_messages``.  An
  earlier revision only reminded the operator to disable it by hand, and a
  sandbox run then reported zero inbound updates with no stated cause.

The single-bot design is deliberate: Telegram never delivers messages from one
bot to another, so a second bot cannot be the sender.  See the script docstring.
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

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "telegram_sandbox_preflight.py"
)

# Synthetic, non-functional token shapes -- never real credentials.
FAKE_TOKEN_A = "111111111:AAFakeTokenValueForTestsOnly_000000000000"
FAKE_BOT_RESPONSE = {
    "ok": True,
    "result": {
        "id": 987654321,
        "is_bot": True,
        "first_name": "SyntheticBot",
        "username": "synthetic_evidence_bot",
        "can_read_all_group_messages": True,
    },
}

# The preflight validates config before use, so the tests must present a
# complete, self-consistent local profile rather than relying on the real .env.
_ENV_DEFAULTS = {
    "APP_ENV": "local",
    "DOCS_PATH": "docs",
    "INDEX_PATH": ".runtime/index.sqlite3",
    "TELEGRAM_POLL_TIMEOUT_SECONDS": "30",
    "TELEGRAM_REQUEST_TIMEOUT_SECONDS": "4",
    "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
    "LLM_MODEL": "synthetic-model",
    "LLM_TIMEOUT_SECONDS": "3",
    "MAX_QUESTION_CHARS": "2000",
    "LOG_LEVEL": "info",
}


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Keep these tests independent of the developer's real .env file."""
    for key, value in _ENV_DEFAULTS.items():
        monkeypatch.setenv(key, value)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "telegram_sandbox_preflight", SCRIPT_PATH
    )
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


def test_probe_reports_only_coarse_status(module):
    """A healthy probe returns capability flags and nothing identifying."""
    status, fields = module.probe(FAKE_TOKEN_A, _responder(200, FAKE_BOT_RESPONSE))

    assert status == module._ACCEPTED
    assert fields == {"http_status": 200, "is_bot": True, "privacy_off": True}
    rendered = json.dumps(fields)
    assert FAKE_TOKEN_A not in rendered
    assert "987654321" not in rendered
    assert "synthetic_evidence_bot" not in rendered


def test_probe_never_echoes_token_on_rejection(module):
    status, fields = module.probe(FAKE_TOKEN_A, _responder(401))

    assert status == module._REJECTED
    assert fields["error_category"] == "TELEGRAM_UNAUTHORIZED"
    assert FAKE_TOKEN_A not in json.dumps(fields)


def test_probe_categorises_transport_failure_without_url(module):
    """The token lives in the request URL, so the URL must never be echoed."""

    def failing(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("synthetic connect failure")

    status, fields = module.probe(FAKE_TOKEN_A, failing)

    assert status == module._UNREACHABLE
    assert fields == {"error_category": "TELEGRAM_UNREACHABLE"}
    assert FAKE_TOKEN_A not in json.dumps(fields)


def test_probe_reports_privacy_mode_off_from_api(module):
    """Privacy mode comes from the API flag, not from the operator's memory."""
    response = json.loads(json.dumps(FAKE_BOT_RESPONSE))
    response["result"]["can_read_all_group_messages"] = False

    _status, fields = module.probe(FAKE_TOKEN_A, _responder(200, response))

    assert fields["privacy_off"] is False


def test_sanitize_removes_token_and_bot_id_shapes(module):
    """Defence in depth: any string routed through _sanitize loses secrets.

    ``_sanitize`` deliberately does NOT strip bare integers -- a numeric id on
    its own is not a secret and stripping every number would mangle harmless
    output such as counts and timings.  It strips the token shape and the
    ``bot<id>`` handle form, which is where a real leak would appear.
    """
    bot_id = FAKE_BOT_RESPONSE["result"]["id"]
    text = f"failed for bot{bot_id} with token {FAKE_TOKEN_A}"
    cleaned = module._sanitize(text)

    assert FAKE_TOKEN_A not in cleaned
    assert f"bot{bot_id}" not in cleaned
    assert "[REDACTED]" in cleaned


def test_token_shape_accepts_valid_and_rejects_pasted_noise(module):
    """A pasted-wrong value should fail as a shape error, not a confusing 401."""
    assert module.TOKEN_SHAPE.match(FAKE_TOKEN_A)
    assert not module.TOKEN_SHAPE.match("")
    assert not module.TOKEN_SHAPE.match('"111111111:AAabc"')
    assert not module.TOKEN_SHAPE.match("111111111")
    assert not module.TOKEN_SHAPE.match("not-a-token-at-all")


def test_missing_token_is_not_ready(module, tmp_path, monkeypatch):
    """No application token => NOT_READY, and never a silent pass."""
    monkeypatch.delenv(module.BOT_A_VAR, raising=False)
    # Point at an empty project dir so no .env supplies the value either.
    monkeypatch.setattr(
        sys, "argv", ["telegram_sandbox_preflight.py", "--project-root", str(tmp_path)]
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = module.main()

    output = captured.getvalue()
    assert exit_code == 4
    assert "verdict=NOT_READY" in output
    assert "reason=bot_a_token_missing" in output


def test_mis_shaped_token_is_not_ready_with_shape_reason(module, tmp_path, monkeypatch):
    """A quoted or truncated value names ``token_shape_invalid``, not auth failure."""
    monkeypatch.setenv(module.BOT_A_VAR, '"111111111:AAabc"')
    monkeypatch.setattr(
        sys, "argv", ["telegram_sandbox_preflight.py", "--project-root", str(tmp_path)]
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = module.main()

    output = captured.getvalue()
    assert exit_code == 4
    assert "reason=token_shape_invalid" in output
    assert "111111111:AAabc" not in output


def test_privacy_mode_enabled_blocks_readiness(module, tmp_path, monkeypatch):
    """Privacy ON is a NOT_READY verdict, not a printed reminder.

    A bot with privacy mode ON only receives commands and replies directed at
    it, so the operator's plain question never arrives.  Detecting it here is
    what stops the sandbox from reporting an unexplained empty run.
    """
    monkeypatch.setenv(module.BOT_A_VAR, FAKE_TOKEN_A)
    response = json.loads(json.dumps(FAKE_BOT_RESPONSE))
    response["result"]["can_read_all_group_messages"] = False
    # Bind the real function before patching, so the stand-in does not recurse.
    real_probe = module.probe
    monkeypatch.setattr(
        module, "probe", lambda token, get=None: real_probe(token, _responder(200, response))
    )
    monkeypatch.setattr(
        sys, "argv", ["telegram_sandbox_preflight.py", "--project-root", str(tmp_path)]
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = module.main()

    output = captured.getvalue()
    assert exit_code == 4
    assert "reason=privacy_mode_still_enabled" in output
    assert "bot_a_privacy_off=False" in output
    assert FAKE_TOKEN_A not in output


def test_healthy_bot_passes_no_network_shape_check(module, tmp_path, monkeypatch):
    """A well-shaped token is enough for the offline check."""
    monkeypatch.setenv(module.BOT_A_VAR, FAKE_TOKEN_A)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "telegram_sandbox_preflight.py",
            "--project-root",
            str(tmp_path),
            "--no-network",
        ],
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = module.main()

    output = captured.getvalue()
    assert exit_code == 0
    assert "verdict=READY_SHAPE_ONLY" in output
    assert FAKE_TOKEN_A not in output
