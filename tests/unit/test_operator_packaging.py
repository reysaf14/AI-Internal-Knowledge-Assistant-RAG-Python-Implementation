"""M6 operator packaging and fail-fast configuration checks."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from rag_assistant.config import (
    load_config,
    load_env_file,
    load_operator_env,
    validate_runtime_config,
)


def _required_env(monkeypatch: pytest.MonkeyPatch, *, profile: str = "local") -> None:
    monkeypatch.setenv("APP_ENV", profile)
    monkeypatch.setenv("DOCS_PATH", "docs")
    monkeypatch.setenv("INDEX_PATH", ".runtime/index.sqlite3")


def test_local_env_file_is_explicit_and_process_values_win(tmp_path: Path, monkeypatch):
    """The CLI loader reads local .env without overriding injected values."""
    (tmp_path / ".env").write_text(
        "APP_ENV=local\nDOCS_PATH=docs\nINDEX_PATH=.runtime/from-file.sqlite3\n",
        encoding="utf-8",
    )
    for key in ("APP_ENV", "DOCS_PATH", "INDEX_PATH"):
        monkeypatch.delenv(key, raising=False)
    load_operator_env(tmp_path)
    monkeypatch.setenv("INDEX_PATH", ".runtime/from-process.sqlite3")

    cfg = load_config(tmp_path)

    assert cfg.app_env == "local"
    assert cfg.docs_path == Path("docs")
    assert cfg.index_path == Path(".runtime/from-process.sqlite3")


def test_env_file_loader_accepts_quoted_values_and_never_executes(tmp_path: Path, monkeypatch):
    """Quoted data is parsed as data, with no interpolation or shell execution."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SAFE_VALUE=\"literal $NOT_EXPANDED\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SAFE_VALUE", raising=False)

    load_env_file(env_file)

    assert os.environ["SAFE_VALUE"] == "literal $NOT_EXPANDED"


def test_env_file_malformed_line_fails_closed(tmp_path: Path):
    """Malformed operator configuration exits before application side effects."""
    env_file = tmp_path / ".env"
    env_file.write_text("not-an-assignment\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="3"):
        load_env_file(env_file)


def test_runtime_validation_accepts_local_ingest(tmp_path: Path, monkeypatch):
    """The valid project docs boundary is accepted before rebuild."""
    (tmp_path / "docs").mkdir()
    _required_env(monkeypatch)
    cfg = load_config(tmp_path)

    validate_runtime_config(cfg, "ingest")


def test_runtime_validation_rejects_docs_outside_project_boundary(
    tmp_path: Path, monkeypatch
):
    """Ingest cannot write an index from an unapproved docs boundary."""
    outside_docs = tmp_path / "other-docs"
    outside_docs.mkdir()
    _required_env(monkeypatch)
    monkeypatch.setenv("DOCS_PATH", str(outside_docs))
    cfg = load_config(tmp_path)

    with pytest.raises(SystemExit, match="3"):
        validate_runtime_config(cfg, "ingest")


def test_runtime_validation_rejects_bot_without_token_or_active_index(
    tmp_path: Path, monkeypatch
):
    """Bot readiness fails before network or state writes when prerequisites miss."""
    _required_env(monkeypatch)
    cfg = load_config(tmp_path)

    with pytest.raises(SystemExit, match="3"):
        validate_runtime_config(cfg, "bot")


def test_runtime_validation_accepts_bot_with_token_and_index(
    tmp_path: Path, monkeypatch
):
    """Bot readiness accepts the required names without contacting Telegram."""
    runtime_dir = tmp_path / ".runtime"
    runtime_dir.mkdir()
    (runtime_dir / "index.sqlite3").write_bytes(b"synthetic-index-placeholder")
    _required_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setenv("LLM_MODEL", "Qwen8B-synthetic")
    cfg = load_config(tmp_path)

    validate_runtime_config(cfg, "bot")
