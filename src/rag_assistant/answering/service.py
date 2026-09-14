"""Answer service: retrieval context to validated answer.

This is the M3 failure-control boundary.  It fails closed: insufficient
context, a model timeout, a provider failure, an unparseable provider
response, or an unsourceable answer each produce the canonical abstention with
no sources and no success claim.

The application deadline is enforced by this service, independently of the
client.  A provider that ignores its own timeout still cannot make the service
report a late answer as successful.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from rag_assistant.answering.adapter import (
    ChatMessage,
    HttpModelClient,
    ModelClient,
    ModelError,
    ModelTimeoutError,
)
from rag_assistant.answering.prompts import ABSTENTION_TEXT, build_messages
from rag_assistant.answering.validator import validate_model_answer
from rag_assistant.config import AppConfig
from rag_assistant.domain.types import AnswerResult, RetrievalResult
from rag_assistant.observability.logger import SanitizedLogger
from rag_assistant.retrieval.grounding import build_grounded_context

DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_MAX_CONTEXT_CHUNKS = 5

LOGGER_NAME = "rag_assistant.answering"

STATUS_OK = "ok"
STATUS_ABSTAIN = "abstain"
STATUS_ERROR = "error"


class AnswerService:
    """Produce a grounded answer or a safe abstention, never both."""

    def __init__(
        self,
        client: ModelClient,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_context_chunks: int = DEFAULT_MAX_CONTEXT_CHUNKS,
        logger: SanitizedLogger | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_context_chunks < 1:
            raise ValueError("max_context_chunks must be positive")
        self._client = client
        self._timeout_seconds = float(timeout_seconds)
        self._max_context_chunks = max_context_chunks
        self._logger = logger or SanitizedLogger(LOGGER_NAME)

    def answer(self, question: str, retrieval: RetrievalResult) -> AnswerResult:
        """Answer from validated context, or abstain safely."""
        started_at = time.monotonic()

        grounded = build_grounded_context(
            retrieval, max_chunks=self._max_context_chunks
        )
        if not grounded.valid or grounded.context is None:
            return self._abstain(
                "unsupported_context",
                started_at=started_at,
                corpus_version=retrieval.corpus_version,
                context_chunks=0,
            )

        context = grounded.context
        messages = build_messages(context, question)

        try:
            raw_answer = self._complete(messages)
        except ModelError as exc:
            return self._abstain(
                exc.category,
                started_at=started_at,
                corpus_version=context.corpus_version,
                context_chunks=len(context.chunks),
                status=STATUS_ERROR,
            )

        validated = validate_model_answer(raw_answer, context)
        if not validated.result.supported:
            return self._abstain(
                validated.reason,
                started_at=started_at,
                corpus_version=context.corpus_version,
                context_chunks=len(context.chunks),
            )

        self._log(
            status=STATUS_OK,
            started_at=started_at,
            corpus_version=context.corpus_version,
            context_chunks=len(context.chunks),
            reason="",
            source_count=len(validated.result.sources),
        )
        return validated.result

    def _complete(self, messages: list[ChatMessage]) -> str:
        """Call the client under an application-owned wall-clock deadline."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-model")
        future = executor.submit(self._client.complete, messages, self._timeout_seconds)
        try:
            return future.result(timeout=self._timeout_seconds)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise ModelTimeoutError(
                f"model exceeded the {self._timeout_seconds}s deadline"
            ) from exc
        finally:
            executor.shutdown(wait=False)

    def _abstain(
        self,
        reason: str,
        *,
        started_at: float,
        corpus_version: str,
        context_chunks: int,
        status: str = STATUS_ABSTAIN,
    ) -> AnswerResult:
        self._log(
            status=status,
            started_at=started_at,
            corpus_version=corpus_version,
            context_chunks=context_chunks,
            reason=reason,
            source_count=0,
        )
        return AnswerResult(
            text=ABSTENTION_TEXT,
            sources=[],
            supported=False,
            abstained=True,
        )

    def _log(
        self,
        *,
        status: str,
        started_at: float,
        corpus_version: str,
        context_chunks: int,
        reason: str,
        source_count: int,
    ) -> None:
        """Log technical metadata only.

        The question text, the model output, the context text, and any source
        body are never written to the log.
        """
        metadata = {"context_chunks": str(context_chunks)}
        if reason:
            metadata["reason"] = reason
        if status == STATUS_OK:
            metadata["source_count"] = str(source_count)
        self._logger.log_operation(
            operation="answer",
            status=status,
            duration_ms=(time.monotonic() - started_at) * 1000,
            corpus_version=corpus_version,
            error_category=reason if status == STATUS_ERROR else "",
            **metadata,
        )


def build_answer_service(
    cfg: AppConfig, client: ModelClient | None = None
) -> AnswerService:
    """Wire configuration and the default HTTP adapter into a service."""
    model_client = client or HttpModelClient(
        base_url=cfg.llm_base_url,
        model_name=cfg.llm_model,
        api_key=cfg.llm_api_key or None,
    )
    return AnswerService(model_client, timeout_seconds=float(cfg.llm_timeout))
