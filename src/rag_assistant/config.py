"""Configuration loading and validation.

Reads from process environment. Validates required variables before any side effect.
Path resolution is relative to project root.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_VALID_PROFILES = {"local", "test", "vps"}
_VALID_OPERATIONS = {"ingest", "bot"}
_ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VALID_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}

_REQUIRED_KEYS = [
    "APP_ENV",
    "DOCS_PATH",
    "INDEX_PATH",
]

# ``RAG_CONTEXT_LIMIT`` is documented as model-dependent in ADR-002: it is the
# retrieval breadth handed to the answering model, not a calibrated M2 gate.
# Generic LLM endpoint keys. ``LLM_*`` is the current name and ``MODEL_*`` is
# accepted as a legacy fallback so an environment written against
# environment-schema v1.0 keeps working unchanged.  The API key is optional:
# an empty value means "no auth header" (local model), a value enables
# ``Authorization: Bearer <key>``.  The key value is never logged.
#
# ``LLM_TIMEOUT_SECONDS`` default is 30, raised from 3 by ADR-004.  The budget
# must cover a model that is not resident yet: a local model endpoint unloads an
# idle model (Ollama's default is roughly five minutes) and the next request
# pays a one-off cold load of ~26 s.  At 3 s that request always timed out, and
# every timeout is answered with a fixed "tidak menemukan informasi yang cukup"
# line -- which the caller cannot distinguish from a genuine abstention.  A warm
# answer costs ~1-4 s, so 30 s leaves the steady state untouched and only
# absorbs the cold path.  This is a ceiling, not a target: ``REQ-006`` still
# measures delivered latency against its own threshold.
_OPTIONAL_DEFAULTS: dict[str, str] = {
    "TELEGRAM_POLL_TIMEOUT_SECONDS": "30",
    "TELEGRAM_REQUEST_TIMEOUT_SECONDS": "4",
    "LLM_BASE_URL": "http://127.0.0.1:8080/v1",
    "LLM_MODEL": "local-default",
    "LLM_TIMEOUT_SECONDS": "30",
    "MAX_QUESTION_CHARS": "2000",
    "LOG_LEVEL": "info",
    "RAG_CONTEXT_LIMIT": "5",
}

# Current key -> legacy key accepted when the current one is unset or empty.
_LEGACY_ENV_ALIASES: dict[str, str] = {
    "LLM_BASE_URL": "MODEL_BASE_URL",
    "LLM_MODEL": "MODEL_NAME",
    "LLM_TIMEOUT_SECONDS": "MODEL_TIMEOUT_SECONDS",
}


def _env_value(key: str) -> str:
    """Read a key, falling back to its legacy alias, then to the default."""
    value = os.environ.get(key, "").strip()
    if value:
        return value
    legacy = _LEGACY_ENV_ALIASES.get(key)
    if legacy:
        legacy_value = os.environ.get(legacy, "").strip()
        if legacy_value:
            return legacy_value
    return _OPTIONAL_DEFAULTS[key]


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration."""

    app_env: str
    docs_path: Path
    index_path: Path
    telegram_poll_timeout: int = 30
    telegram_request_timeout: int = 4
    telegram_bot_token: str = ""
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_api_key: str = ""
    llm_model: str = "local-default"
    llm_timeout: int = 30
    max_question_chars: int = 2000
    log_level: str = "info"
    # Retrieval breadth.  This is the one retrieval parameter whose best value
    # depends on the answering model (see ADR-002 and
    # rag_assistant.retrieval.service.DEFAULT_CONTEXT_LIMIT).  Default 5 is the
    # value the approved M2/M5 measurements were taken at, so an unset variable
    # reproduces the approved artifact exactly.
    rag_context_limit: int = 5
    expected_file_count: int = 26
    project_root: Path = field(default_factory=lambda: Path.cwd())

    def resolve_index_path(self) -> Path:
        """Return absolute index path resolved against project root."""
        if self.index_path.is_absolute():
            return self.index_path
        return self.project_root / self.index_path

    def resolve_docs_path(self) -> Path:
        """Return absolute docs path resolved against project root."""
        if self.docs_path.is_absolute():
            return self.docs_path
        return self.project_root / self.docs_path


def _diagnostic(category: str, message: str) -> None:
    """Structured error to stderr without leaking values."""
    print(
        f'{{"status":"error","category":"{category}","message":"{message}"}}',
        file=sys.stderr,
    )


def _parse_env_value(value: str) -> str:
    """Parse one safe dotenv value without interpolation or command execution."""
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1]
    return stripped


def load_env_file(path: Path) -> None:
    """Load a simple explicit env file without overriding process variables.

    This is intentionally not called by :func:`load_config`.  The CLI invokes
    it only for the local profile, so tests and VPS launchers cannot silently
    inherit a developer's ``.env``.  Values are treated as data: no expansion,
    command substitution, or shell evaluation is performed.
    """
    if not path.is_file():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        _diagnostic("INVALID_CONFIG", "local env file cannot be read")
        raise SystemExit(3) from None

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            _diagnostic(
                "INVALID_CONFIG", f"env file line {line_number} must use KEY=VALUE"
            )
            raise SystemExit(3)
        key, value = (part.strip() for part in line.split("=", 1))
        if not _ENV_KEY_PATTERN.fullmatch(key):
            _diagnostic("INVALID_CONFIG", f"env file key on line {line_number} is invalid")
            raise SystemExit(3)
        os.environ.setdefault(key, _parse_env_value(value))


def load_operator_env(project_root: Path) -> None:
    """Explicitly load the local profile file when the CLI is used.

    Process/injected values always win.  ``.env`` is never loaded for the test
    or VPS profiles; those profiles must receive their configuration from the
    selected launcher or process environment.
    """
    profile = os.environ.get("APP_ENV", "").strip()
    if profile in {"", "local"}:
        load_env_file(project_root / ".env")


def _validate_int(name: str, value: str) -> int:
    """Parse and validate positive integer env var."""
    try:
        v = int(value)
    except (ValueError, TypeError):
        _diagnostic("INVALID_CONFIG", f"{name} must be a positive integer")
        raise SystemExit(3)
    if v <= 0:
        _diagnostic("INVALID_CONFIG", f"{name} must be positive")
        raise SystemExit(3)
    return v


def validate_runtime_config(cfg: AppConfig, operation: str) -> None:
    """Validate paths and live-runtime readiness before network or writes."""
    if operation not in _VALID_OPERATIONS:
        _diagnostic("INVALID_CONFIG", "operation must be ingest or bot")
        raise SystemExit(3)

    root = cfg.project_root.resolve()
    docs_path = cfg.resolve_docs_path().resolve()
    index_path = cfg.resolve_index_path().resolve()
    expected_docs_root = (root / "docs").resolve()
    expected_runtime_root = (root / ".runtime").resolve()
    errors: list[str] = []

    if operation == "ingest":
        if not docs_path.is_dir():
            errors.append("DOCS_PATH directory does not exist")
        elif expected_docs_root not in (docs_path, *docs_path.parents):
            errors.append("DOCS_PATH must remain under the project docs directory")

    if expected_runtime_root not in (index_path.parent, *index_path.parent.parents):
        errors.append("INDEX_PATH must remain under the project .runtime directory")

    if operation == "bot":
        if not cfg.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required for the bot runtime")
        if not index_path.is_file():
            errors.append("INDEX_PATH active index does not exist; run ingest first")
        if not cfg.llm_base_url or cfg.llm_base_url == "REPLACE_ME":
            errors.append("LLM_BASE_URL is required for the bot runtime")
        if not cfg.llm_model or cfg.llm_model in {"REPLACE_ME", "local-default"}:
            errors.append("LLM_MODEL must be a concrete model identifier for the bot runtime")

    if cfg.log_level not in _VALID_LOG_LEVELS:
        errors.append("LOG_LEVEL must be one of: debug, info, warning, error, critical")

    if errors:
        _diagnostic("INVALID_CONFIG", "; ".join(errors))
        raise SystemExit(3)


def load_config(project_root: Path | None = None) -> AppConfig:
    """Load and validate configuration from process environment.

    Required vars that are missing or placeholder cause immediate exit (code 3).
    Optional vars fall back to documented defaults.
    No .env file is loaded automatically; caller controls env injection.
    """
    root = project_root or Path.cwd()

    profile = os.environ.get("APP_ENV", "").strip()
    if not profile or profile not in _VALID_PROFILES:
        _diagnostic("INVALID_CONFIG", "APP_ENV must be one of: local, test, vps")
        raise SystemExit(3)

    for key in _REQUIRED_KEYS:
        val = os.environ.get(key, "").strip()
        if not val or val == "REPLACE_ME":
            _diagnostic(
                "INVALID_CONFIG",
                f"{key} is required and must not be empty or placeholder",
            )
            raise SystemExit(3)

    docs_path = Path(os.environ["DOCS_PATH"].strip())
    index_path = Path(os.environ["INDEX_PATH"].strip())

    cfg = AppConfig(
        app_env=profile,
        docs_path=docs_path,
        index_path=index_path,
        telegram_poll_timeout=_validate_int(
            "TELEGRAM_POLL_TIMEOUT_SECONDS",
            os.environ.get(
                "TELEGRAM_POLL_TIMEOUT_SECONDS",
                _OPTIONAL_DEFAULTS["TELEGRAM_POLL_TIMEOUT_SECONDS"],
            ),
        ),
        telegram_request_timeout=_validate_int(
            "TELEGRAM_REQUEST_TIMEOUT_SECONDS",
            os.environ.get(
                "TELEGRAM_REQUEST_TIMEOUT_SECONDS",
                _OPTIONAL_DEFAULTS["TELEGRAM_REQUEST_TIMEOUT_SECONDS"],
            ),
        ),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        llm_base_url=_env_value("LLM_BASE_URL"),
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_model=_env_value("LLM_MODEL"),
        llm_timeout=_validate_int(
            "LLM_TIMEOUT_SECONDS", _env_value("LLM_TIMEOUT_SECONDS")
        ),
        max_question_chars=_validate_int(
            "MAX_QUESTION_CHARS",
            os.environ.get(
                "MAX_QUESTION_CHARS", _OPTIONAL_DEFAULTS["MAX_QUESTION_CHARS"]
            ),
        ),
        log_level=os.environ.get(
            "LOG_LEVEL", _OPTIONAL_DEFAULTS["LOG_LEVEL"]
        ).strip().lower(),
        rag_context_limit=_validate_int(
            "RAG_CONTEXT_LIMIT",
            os.environ.get(
                "RAG_CONTEXT_LIMIT", _OPTIONAL_DEFAULTS["RAG_CONTEXT_LIMIT"]
            ),
        ),
        project_root=root,
    )

    return cfg
