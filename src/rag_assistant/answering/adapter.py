"""Generic model adapter for an OpenAI-compatible chat endpoint.

The design deliberately does not lock a provider; the Engineer chooses the wire
format and a local test double.  This adapter:

* speaks a minimal OpenAI-compatible ``POST <base>/chat/completions`` shape;
* converts every provider failure into a typed, controllable error so the
  answering boundary can fail closed;
* never logs or propagates raw provider payloads, headers, or credentials.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

CATEGORY_TIMEOUT = "MODEL_TIMEOUT"
CATEGORY_PROVIDER = "MODEL_PROVIDER"
CATEGORY_INVALID_RESPONSE = "MODEL_INVALID_RESPONSE"
CATEGORY_ERROR = "MODEL_ERROR"

DEFAULT_MAX_TOKENS = 512


class ModelError(Exception):
    """Controlled model failure; never carries a provider payload."""

    category = CATEGORY_ERROR


class ModelTimeoutError(ModelError):
    """The model call exceeded the application deadline."""

    category = CATEGORY_TIMEOUT


class ModelProviderError(ModelError):
    """The provider was unreachable or returned an HTTP error status."""

    category = CATEGORY_PROVIDER


class ModelInvalidResponseError(ModelError):
    """The provider returned an empty, unparseable, or out-of-contract body."""

    category = CATEGORY_INVALID_RESPONSE


@dataclass(frozen=True)
class ChatMessage:
    """One chat message in the minimal OpenAI-compatible shape."""

    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        """Return the wire representation of this message."""
        return {"role": self.role, "content": self.content}


class ModelClient(Protocol):
    """Boundary the answer service depends on.

    Unit tests implement this protocol with a local double so no test touches
    the network.
    """

    def complete(
        self, messages: Sequence[ChatMessage], timeout_seconds: float
    ) -> str:
        """Return assistant text or raise a :class:`ModelError`."""
        ...


class HttpModelClient:
    """OpenAI-compatible HTTP client implementing :class:`ModelClient`."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        *,
        api_key: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required")
        if not model_name or not model_name.strip():
            raise ValueError("model_name is required")
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._api_key = (api_key or "").strip()
        self._max_tokens = max_tokens
        self._client = http_client

    def endpoint(self) -> str:
        """Return the chat-completions endpoint URL (no credentials involved)."""
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        """Build request headers.

        The API key is placed only in this header and is never logged, never
        included in the payload, and never attached to a raised error message.
        """
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(
        self, messages: Sequence[ChatMessage], timeout_seconds: float
    ) -> str:
        """Send one chat completion request and return its text content."""
        payload = {
            "model": self._model_name,
            "messages": [message.as_dict() for message in messages],
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
        }

        try:
            response = self._post(payload, timeout_seconds)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(
                f"model call exceeded {timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError("model endpoint unreachable") from exc

        if response.status_code >= 400:
            raise ModelProviderError(
                f"model provider returned HTTP {response.status_code}"
            )

        try:
            data: Any = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelInvalidResponseError(
                "model response was not parseable"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelInvalidResponseError("model response content was empty")

        return content.strip()

    def _post(self, payload: dict[str, Any], timeout_seconds: float) -> httpx.Response:
        headers = self._headers()
        if self._client is not None:
            return self._client.post(
                self.endpoint(),
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
        with httpx.Client(timeout=timeout_seconds) as client:
            return client.post(self.endpoint(), json=payload, headers=headers)


class OllamaModelClient:
    """Native Ollama chat client with reasoning explicitly disabled.

    Ollama's OpenAI-compatible facade does not reliably apply the ``think``
    flag for every local model.  The native endpoint is used only when the
    configured local runtime is known to be Ollama; generic endpoints keep the
    provider-neutral :class:`HttpModelClient` above.
    """

    def __init__(
        self,
        base_url: str,
        model_name: str,
        *,
        api_key: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required")
        if not model_name or not model_name.strip():
            raise ValueError("model_name is required")
        self._base_url = _ollama_base_url(base_url)
        self._model_name = model_name
        self._api_key = (api_key or "").strip()
        self._max_tokens = max_tokens
        self._client = http_client

    def endpoint(self) -> str:
        """Return the native Ollama chat endpoint."""
        return f"{self._base_url}/api/chat"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(
        self, messages: Sequence[ChatMessage], timeout_seconds: float
    ) -> str:
        """Send one native chat request with Ollama thinking disabled."""
        payload = {
            "model": self._model_name,
            "messages": [message.as_dict() for message in messages],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": self._max_tokens},
        }

        try:
            response = self._post(payload, timeout_seconds)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(
                f"model call exceeded {timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError("model endpoint unreachable") from exc

        if response.status_code >= 400:
            raise ModelProviderError(
                f"model provider returned HTTP {response.status_code}"
            )

        try:
            data: Any = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelInvalidResponseError(
                "model response was not parseable"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelInvalidResponseError("model response content was empty")

        return content.strip()

    def _post(self, payload: dict[str, Any], timeout_seconds: float) -> httpx.Response:
        headers = self._headers()
        if self._client is not None:
            return self._client.post(
                self.endpoint(),
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
        with httpx.Client(timeout=timeout_seconds) as client:
            return client.post(self.endpoint(), json=payload, headers=headers)


def _ollama_base_url(base_url: str) -> str:
    """Normalize a configured Ollama URL to its server root."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized
