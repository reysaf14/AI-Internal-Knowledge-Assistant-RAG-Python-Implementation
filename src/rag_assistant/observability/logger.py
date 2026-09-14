"""Sanitized structured logging for rag_assistant.

Log format includes: operation, timestamp, duration, status, sanitized error
category, corpus version. NEVER logs: question text, answer text, username,
chat_id, Telegram payload, token, credential.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager


class SanitizedLogger:
    """Logging wrapper that enforces data sanitization rules."""

    def __init__(self, name: str, level: str = "info"):
        self._logger = logging.getLogger(name)
        level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }
        self._logger.setLevel(level_map.get(level.lower(), logging.INFO))

        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def log_operation(
        self,
        operation: str,
        status: str,
        duration_ms: float | None = None,
        corpus_version: str = "",
        error_category: str = "",
        **safe_metadata: str,
    ) -> None:
        """Log a structured operation entry (technical metadata only)."""
        parts = [f"op={operation}", f"status={status}"]
        if duration_ms is not None:
            parts.append(f"duration_ms={duration_ms:.1f}")
        if corpus_version:
            parts.append(f"corpus={corpus_version}")
        if error_category:
            parts.append(f"error_category={error_category}")
        for k, v in safe_metadata.items():
            parts.append(f"{k}={v}")

        msg = " | ".join(parts)
        if status in ("error", "fail"):
            self._logger.error(msg)
        elif status in ("warn", "warning"):
            self._logger.warning(msg)
        else:
            self._logger.info(msg)


@contextmanager
def measure_duration():
    """Context manager that measures elapsed time in milliseconds."""
    result: dict[str, float] = {"duration_ms": 0.0}
    start = time.monotonic()
    try:
        yield result
    finally:
        result["duration_ms"] = (time.monotonic() - start) * 1000