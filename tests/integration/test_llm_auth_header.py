"""The HTTP adapter authenticates with a Bearer header and never leaks the key.

The stub binds an ephemeral ``127.0.0.1`` port and records the headers and body
it receives, so the assertion is made against what actually crossed the wire.
No external network, credential, or provider is involved.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rag_assistant.answering import (
    ChatMessage,
    HttpModelClient,
    ModelProviderError,
)

SENT_HEADERS: list[dict[str, str]] = []
SENT_BODIES: list[str] = []
DUMMY_KEY = "dummy-router-key-not-real"


class _RecordingStub(BaseHTTPRequestHandler):
    """Records each request and replies with a minimal chat-completions body."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        SENT_HEADERS.append({key.lower(): value for key, value in self.headers.items()})
        SENT_BODIES.append(raw.decode("utf-8", "replace"))

        status = getattr(self.server, "status", 200)
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            # Client already disconnected (expected in the failure cases).
            pass

    def log_message(self, *args: object) -> None:
        """Keep stub access logging out of the test output."""


@pytest.fixture
def stub() -> Iterator[Callable[..., str]]:
    """Start recording stubs on demand and always shut them down."""
    SENT_HEADERS.clear()
    SENT_BODIES.clear()
    servers: list[ThreadingHTTPServer] = []

    def _start(status: int = 200) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingStub)
        server.status = status
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        host, port = server.server_address
        return f"http://{host}:{port}"

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="halo")]


def test_api_key_is_sent_as_bearer_header(stub: Callable[..., str]):
    """An API key becomes exactly one Authorization: Bearer header."""
    client = HttpModelClient(stub(), "generic-model", api_key=DUMMY_KEY)

    assert client.complete(_messages(), 2.0) == "ok"
    assert SENT_HEADERS[-1].get("authorization") == f"Bearer {DUMMY_KEY}"


def test_no_authorization_header_without_api_key(stub: Callable[..., str]):
    """A local endpoint without a key sends no Authorization header."""
    client = HttpModelClient(stub(), "generic-model")

    assert client.complete(_messages(), 2.0) == "ok"
    assert "authorization" not in SENT_HEADERS[-1]


def test_api_key_is_not_placed_in_the_request_body(stub: Callable[..., str]):
    """The key travels only in the header, never in the payload."""
    client = HttpModelClient(stub(), "generic-model", api_key=DUMMY_KEY)

    client.complete(_messages(), 2.0)

    assert DUMMY_KEY not in SENT_BODIES[-1]
    assert "authorization" not in SENT_BODIES[-1].lower()


def test_provider_error_message_does_not_leak_the_api_key(stub: Callable[..., str]):
    """A failing endpoint must not echo the credential into a raised error."""
    client = HttpModelClient(stub(status=500), "generic-model", api_key=DUMMY_KEY)

    with pytest.raises(ModelProviderError) as excinfo:
        client.complete(_messages(), 2.0)

    assert DUMMY_KEY not in str(excinfo.value)


def test_blank_api_key_is_treated_as_absent(stub: Callable[..., str]):
    """An empty env value must not produce an empty Bearer header."""
    client = HttpModelClient(stub(), "generic-model", api_key="")

    client.complete(_messages(), 2.0)

    assert "authorization" not in SENT_HEADERS[-1]
