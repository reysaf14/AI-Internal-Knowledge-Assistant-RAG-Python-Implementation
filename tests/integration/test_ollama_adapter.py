"""Local Ollama adapter contract tests using an in-process HTTP boundary."""
from __future__ import annotations

import json

import httpx

from rag_assistant.answering import ChatMessage, OllamaModelClient


def test_native_ollama_client_disables_thinking_and_uses_native_endpoint():
    """The local model request carries think=false and the native path."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "local-ok"}},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OllamaModelClient(
            "http://127.0.0.1:11434/v1",
            "gemma4:e2b-it-qat",
            http_client=http_client,
        )
        assert (
            client.complete([ChatMessage(role="user", content="ping")], 2.0)
            == "local-ok"
        )

    assert seen["path"] == "/api/chat"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["think"] is False
    assert body["stream"] is False
