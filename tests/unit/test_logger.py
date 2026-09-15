"""Unit tests for sanitized logging."""
import logging

from rag_assistant.observability.logger import SanitizedLogger, measure_duration


def test_logger_configured():
    """Logger is created with handlers."""
    logger = SanitizedLogger("test_logger", level="info")
    assert logger._logger.level == logging.INFO


def test_log_operation_sanitized(caplog):
    """Log operation includes technical metadata, not payload."""
    logger = SanitizedLogger("test_log_sanitized", level="info")
    with caplog.at_level(logging.INFO, logger="test_log_sanitized"):
        logger.log_operation(
            operation="corpus_rebuild",
            status="ok",
            duration_ms=12.3,
            corpus_version="abc123",
        )
    assert any("corpus_rebuild" in r.message for r in caplog.records)
    assert any("corpus=abc123" in r.message for r in caplog.records)


def test_measure_duration():
    """measure_duration records elapsed time."""
    with measure_duration() as m:
        pass
    assert m["duration_ms"] >= 0