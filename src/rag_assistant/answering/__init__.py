"""Answering boundary: model adapter, answer validation, and failure control."""

from rag_assistant.answering.adapter import (
    ChatMessage,
    HttpModelClient,
    ModelClient,
    ModelError,
    ModelInvalidResponseError,
    ModelProviderError,
    ModelTimeoutError,
    OllamaModelClient,
)
from rag_assistant.answering.prompts import (
    ABSTENTION_TEXT,
    SYSTEM_INSTRUCTIONS,
    build_messages,
    format_answer,
)
from rag_assistant.answering.service import AnswerService, build_answer_service
from rag_assistant.answering.validator import (
    ValidatedAnswer,
    validate_model_answer,
)

__all__ = [
    "ABSTENTION_TEXT",
    "SYSTEM_INSTRUCTIONS",
    "AnswerService",
    "ChatMessage",
    "HttpModelClient",
    "ModelClient",
    "ModelError",
    "ModelInvalidResponseError",
    "ModelProviderError",
    "ModelTimeoutError",
    "OllamaModelClient",
    "ValidatedAnswer",
    "build_answer_service",
    "build_messages",
    "format_answer",
    "validate_model_answer",
]
