"""DeepSeek OpenAI-compatible request contract, verified without network."""
from __future__ import annotations

import json

import httpx

from rag_assistant.answering import ChatMessage, HttpModelClient
from rag_assistant.answering.service import _build_configured_model_client
from rag_assistant.config import load_config


def test_deepseek_request_uses_auth_and_explicit_thinking_off():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "mock answer"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = HttpModelClient(
            "https://api.deepseek.com",
            "deepseek-flash",
            api_key="synthetic-key-not-a-secret",
            disable_thinking=True,
            http_client=http_client,
        )
        answer = client.complete([ChatMessage("user", "synthetic question")], 2.0)

    assert answer == "mock answer"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["authorization"] == "Bearer synthetic-key-not-a-secret"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}


def test_configured_deepseek_client_disables_thinking(tmp_path, monkeypatch):
    for key in (
        "APP_ENV",
        "DOCS_PATH",
        "INDEX_PATH",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DOCS_PATH", "docs")
    monkeypatch.setenv("INDEX_PATH", ".runtime/index.sqlite3")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-key")
    cfg = load_config(tmp_path)

    client = _build_configured_model_client(cfg)

    assert isinstance(client, HttpModelClient)
    assert client._disable_thinking is True


def test_generic_openai_compatible_client_does_not_receive_deepseek_options():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "generic answer"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = HttpModelClient(
            "https://router.example/v1",
            "generic-model",
            http_client=http_client,
        )
        client.complete([ChatMessage("user", "synthetic question")], 2.0)

    body = seen["body"]
    assert isinstance(body, dict)
    assert "thinking" not in body
