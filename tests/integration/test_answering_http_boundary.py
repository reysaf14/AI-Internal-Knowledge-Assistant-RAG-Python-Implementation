"""M3 integration: the real HTTP model adapter against a local stub server.

The stub binds an ephemeral port on ``127.0.0.1``.  No external network,
credential, provider, or production record is involved; this exercises the
actual ``httpx`` code path rather than the protocol double used by unit tests.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rag_assistant.answering import (
    ABSTENTION_TEXT,
    AnswerService,
    ChatMessage,
    HttpModelClient,
    ModelInvalidResponseError,
    ModelProviderError,
    ModelTimeoutError,
)
from rag_assistant.config import AppConfig
from rag_assistant.ingestion.builder import rebuild_corpus
from rag_assistant.retrieval import Retriever
from rag_assistant.storage.index_store import IndexStore

SUPPORTED_QUESTION = "Apa saja metode pembayaran yang diterima?"
GROUNDED_CONTENT = (
    "Toko menerima tunai, kartu debit, kartu kredit, dan QRIS.\n"
    "SUMBER: 02_FAQ_Pembayaran.md"
)


class _StubHandler(BaseHTTPRequestHandler):
    """Minimal chat-completions stub driven by ``server.mode``."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        mode = self.server.mode
        if mode == "slow":
            time.sleep(self.server.delay)
        if mode == "http_500":
            self._respond(500, b'{"error":"upstream"}')
            return
        if mode == "invalid_json":
            self._respond(200, b"not-json")
            return
        if mode == "empty_content":
            self._respond(200, _payload({"choices": [{"message": {"content": "  "}}]}))
            return
        if mode == "no_source":
            self._respond(
                200,
                _payload({"choices": [{"message": {"content": "Toko menerima tunai."}}]}),
            )
            return
        self._respond(200, _payload({"choices": [{"message": {"content": GROUNDED_CONTENT}}]}))

    def _respond(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            # Client already disconnected (expected in the timeout cases).
            pass

    def log_message(self, *args: object) -> None:
        """Keep stub access logging out of the test output."""


def _payload(body: dict) -> bytes:
    return json.dumps(body).encode("utf-8")


@pytest.fixture
def stub_server() -> Iterator[object]:
    """Start local stub servers on demand and always shut them down."""
    servers: list[ThreadingHTTPServer] = []

    def _start(mode: str = "ok", delay: float = 0.0) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        server.mode = mode
        server.delay = delay
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        host, port = server.server_address
        return f"http://{host}:{port}"

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def _retriever(tmp_path: Path, synthetic_docs: Path) -> Retriever:
    cfg = AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )
    assert rebuild_corpus(cfg).success
    return Retriever(IndexStore(cfg.resolve_index_path()))


def test_http_client_parses_a_valid_completion(stub_server):
    """T-M3-HTTP-01: a 200 response is parsed into assistant text."""
    client = HttpModelClient(stub_server("ok"), "stub-model")

    text = client.complete([ChatMessage(role="user", content="halo")], 2.0)

    assert "02_FAQ_Pembayaran.md" in text


def test_http_client_maps_http_error_to_provider_error(stub_server):
    """T-M3-HTTP-02: AC-016 provider failure surfaces as a controlled error."""
    client = HttpModelClient(stub_server("http_500"), "stub-model")

    with pytest.raises(ModelProviderError):
        client.complete([ChatMessage(role="user", content="halo")], 2.0)


def test_http_client_maps_invalid_json_to_invalid_response(stub_server):
    """T-M3-HTTP-03: AC-016 unparseable body surfaces as a controlled error."""
    client = HttpModelClient(stub_server("invalid_json"), "stub-model")

    with pytest.raises(ModelInvalidResponseError):
        client.complete([ChatMessage(role="user", content="halo")], 2.0)


def test_http_client_maps_empty_content_to_invalid_response(stub_server):
    """T-M3-HTTP-04: AC-016 empty content is not a valid answer."""
    client = HttpModelClient(stub_server("empty_content"), "stub-model")

    with pytest.raises(ModelInvalidResponseError):
        client.complete([ChatMessage(role="user", content="halo")], 2.0)


def test_http_client_maps_slow_response_to_timeout(stub_server):
    """T-M3-HTTP-05: AC-015 a slow provider becomes a controlled timeout."""
    client = HttpModelClient(stub_server("slow", delay=0.8), "stub-model")

    with pytest.raises(ModelTimeoutError):
        client.complete([ChatMessage(role="user", content="halo")], 0.3)


def test_pipeline_produces_a_sourced_answer_over_http(
    tmp_path: Path, synthetic_docs: Path, stub_server
):
    """T-M3-HTTP-06: full pipeline returns a grounded answer via real HTTP."""
    retrieval = _retriever(tmp_path, synthetic_docs).retrieve(SUPPORTED_QUESTION)
    service = AnswerService(
        HttpModelClient(stub_server("ok"), "stub-model"), timeout_seconds=2.0
    )

    result = service.answer(SUPPORTED_QUESTION, retrieval)

    assert result.supported
    assert result.sources == ["02_FAQ_Pembayaran.md"]


def test_pipeline_abstains_when_provider_fails(
    tmp_path: Path, synthetic_docs: Path, stub_server
):
    """T-M3-HTTP-07: AC-016 a failing provider cannot produce a success claim."""
    retrieval = _retriever(tmp_path, synthetic_docs).retrieve(SUPPORTED_QUESTION)
    service = AnswerService(
        HttpModelClient(stub_server("http_500"), "stub-model"), timeout_seconds=2.0
    )

    result = service.answer(SUPPORTED_QUESTION, retrieval)

    assert result.abstained
    assert not result.supported
    assert result.sources == []
    assert result.text == ABSTENTION_TEXT


def test_pipeline_abstains_when_provider_times_out(
    tmp_path: Path, synthetic_docs: Path, stub_server
):
    """T-M3-HTTP-08: AC-015 a slow provider yields the safe abstention."""
    retrieval = _retriever(tmp_path, synthetic_docs).retrieve(SUPPORTED_QUESTION)
    service = AnswerService(
        HttpModelClient(stub_server("slow", delay=0.8), "stub-model"),
        timeout_seconds=0.3,
    )

    result = service.answer(SUPPORTED_QUESTION, retrieval)

    assert result.abstained
    assert result.sources == []


def test_pipeline_abstains_when_model_omits_a_source(
    tmp_path: Path, synthetic_docs: Path, stub_server
):
    """T-M3-HTTP-09: AC-017/018 an unsourced answer is not delivered as supported."""
    retrieval = _retriever(tmp_path, synthetic_docs).retrieve(SUPPORTED_QUESTION)
    service = AnswerService(
        HttpModelClient(stub_server("no_source"), "stub-model"), timeout_seconds=2.0
    )

    result = service.answer(SUPPORTED_QUESTION, retrieval)

    assert result.abstained
    assert result.sources == []
