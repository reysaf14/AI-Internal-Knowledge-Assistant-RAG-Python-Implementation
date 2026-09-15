"""Unit tests for configuration loading and validation (AC-033 precursor)."""
from pathlib import Path

import pytest

from rag_assistant.config import load_config


def test_load_config_valid(tmp_path: Path):
    """Valid environment variables produce correct config."""
    env = {
        "APP_ENV": "local",
        "DOCS_PATH": "docs",
        "INDEX_PATH": ".runtime/index.sqlite3",
    }
    with pytest.MonkeyPatch.context() as m:
        for k, v in env.items():
            m.setenv(k, v)
        cfg = load_config(tmp_path)
    assert cfg.app_env == "local"
    assert cfg.docs_path == Path("docs")
    assert cfg.index_path == Path(".runtime/index.sqlite3")
    assert cfg.project_root == tmp_path


def test_load_config_missing_profile(tmp_path: Path):
    """Missing APP_ENV causes exit."""
    with pytest.MonkeyPatch.context() as m:
        m.delenv("APP_ENV", raising=False)
        m.setenv("DOCS_PATH", "docs")
        m.setenv("INDEX_PATH", ".runtime/index.sqlite3")
        with pytest.raises(SystemExit):
            load_config(tmp_path)


def test_load_config_invalid_profile(tmp_path: Path):
    """Invalid APP_ENV value causes exit."""
    with pytest.MonkeyPatch.context() as m:
        m.setenv("APP_ENV", "production")
        m.setenv("DOCS_PATH", "docs")
        m.setenv("INDEX_PATH", ".runtime/index.sqlite3")
        with pytest.raises(SystemExit):
            load_config(tmp_path)


def test_load_config_missing_required(tmp_path: Path):
    """Missing required var causes exit."""
    with pytest.MonkeyPatch.context() as m:
        m.setenv("APP_ENV", "local")
        m.setenv("DOCS_PATH", "docs")
        m.delenv("INDEX_PATH", raising=False)
        with pytest.raises(SystemExit):
            load_config(tmp_path)


def test_load_config_placeholder(tmp_path: Path):
    """Placeholder value for required var causes exit."""
    with pytest.MonkeyPatch.context() as m:
        m.setenv("APP_ENV", "test")
        m.setenv("DOCS_PATH", "REPLACE_ME")
        m.setenv("INDEX_PATH", ".runtime/test.sqlite3")
        with pytest.raises(SystemExit):
            load_config(tmp_path)


def test_load_config_optional_defaults(tmp_path: Path):
    """Optional vars fall back to defaults when not set."""
    env = {
        "APP_ENV": "test",
        "DOCS_PATH": "docs",
        "INDEX_PATH": ".runtime/test.sqlite3",
    }
    with pytest.MonkeyPatch.context() as m:
        for k, v in env.items():
            m.setenv(k, v)
        m.delenv("TELEGRAM_POLL_TIMEOUT_SECONDS", raising=False)
        m.delenv("LOG_LEVEL", raising=False)
        cfg = load_config(tmp_path)
    assert cfg.telegram_poll_timeout == 30
    assert cfg.log_level == "info"


def test_load_config_invalid_optional_int(tmp_path: Path):
    """Invalid optional numeric value causes exit."""
    env = {
        "APP_ENV": "test",
        "DOCS_PATH": "docs",
        "INDEX_PATH": ".runtime/test.sqlite3",
        "TELEGRAM_POLL_TIMEOUT_SECONDS": "-5",
    }
    with pytest.MonkeyPatch.context() as m:
        for k, v in env.items():
            m.setenv(k, v)
        with pytest.raises(SystemExit):
            load_config(tmp_path)