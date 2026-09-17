"""Generic LLM configuration keys (``LLM_*``) and legacy ``MODEL_*`` fallback.

These keys are agent/route agnostic: the endpoint, model, and API key are
configuration, not code.  No secret value is written to disk by these tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_assistant.config import load_config

_LLM_KEYS = (
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
)
_LEGACY_KEYS = (
    "MODEL_BASE_URL",
    "MODEL_NAME",
    "MODEL_TIMEOUT_SECONDS",
)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LLM_KEYS + _LEGACY_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DOCS_PATH", "docs")
    monkeypatch.setenv("INDEX_PATH", ".runtime/index.sqlite3")


def test_llm_keys_are_read_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A generic LLM endpoint, key, model, and timeout are honoured."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "https://router.example/api/v1")
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_MODEL", "router-roundrobin")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "7")

    cfg = load_config(tmp_path)

    assert cfg.llm_base_url == "https://router.example/api/v1"
    assert cfg.llm_api_key == "dummy-not-a-real-key"
    assert cfg.llm_model == "router-roundrobin"
    assert cfg.llm_timeout == 7


def test_defaults_are_used_when_llm_keys_are_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Absent LLM keys fall back to documented defaults, empty API key."""
    _base_env(monkeypatch)

    cfg = load_config(tmp_path)

    assert cfg.llm_base_url == "http://127.0.0.1:8080/v1"
    assert cfg.llm_api_key == ""
    assert cfg.llm_model == "local-default"
    # 30 since ADR-004: the budget must cover a cold model load, not just a warm
    # answer, otherwise every cold request silently degrades to the timeout
    # fallback text.
    assert cfg.llm_timeout == 30


def test_empty_llm_values_fall_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A blank value in an env file must not become an empty config value."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")

    cfg = load_config(tmp_path)

    assert cfg.llm_base_url == "http://127.0.0.1:8080/v1"
    assert cfg.llm_model == "local-default"


def test_legacy_model_keys_are_still_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An environment written against environment-schema v1.0 keeps working."""
    _base_env(monkeypatch)
    monkeypatch.setenv("MODEL_BASE_URL", "http://legacy-host:9000/v1")
    monkeypatch.setenv("MODEL_NAME", "legacy-model")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "5")

    cfg = load_config(tmp_path)

    assert cfg.llm_base_url == "http://legacy-host:9000/v1"
    assert cfg.llm_model == "legacy-model"
    assert cfg.llm_timeout == 5


def test_current_key_wins_over_legacy_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When both are set, the generic LLM_* value takes precedence."""
    _base_env(monkeypatch)
    monkeypatch.setenv("MODEL_BASE_URL", "http://legacy-host:9000/v1")
    monkeypatch.setenv("LLM_BASE_URL", "http://current-host:1234/v1")

    cfg = load_config(tmp_path)

    assert cfg.llm_base_url == "http://current-host:1234/v1"


def test_api_key_is_never_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An unauthenticated local endpoint stays valid without an API key."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")

    cfg = load_config(tmp_path)

    assert cfg.llm_api_key == ""
    assert cfg.llm_base_url.endswith("/v1")


def test_invalid_llm_timeout_stops_before_any_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A non-positive timeout is a configuration error, not a silent default."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "-1")

    with pytest.raises(SystemExit):
        load_config(tmp_path)
