"""Exercise the chat API through the real provider with simulated Ollama HTTP."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.api.chat import get_llm_provider
from app.core.config import Settings
from app.main import create_app
from app.services.llm import LLMProvider
from app.services.ollama import OllamaProvider


def request_chat(
    body: object, handler: Callable[[httpx.Request], httpx.Response]
) -> httpx.Response:
    async def send() -> httpx.Response:
        application = create_app()

        async def override_provider() -> AsyncIterator[LLMProvider]:
            async with httpx.AsyncClient(
                base_url="http://ollama.test:11434",
                transport=httpx.MockTransport(handler),
            ) as client:
                yield OllamaProvider(client, "test-model")

        application.dependency_overrides[get_llm_provider] = override_provider
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            return await client.post("/api/chat", json=body)

    return asyncio.run(send())


def test_chat_sends_question_and_configured_model() -> None:
    def ollama(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://ollama.test:11434/api/chat"
        assert json.loads(request.content) == {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Explain dependency injection."}],
            "stream": False,
        }
        return httpx.Response(
            200, json={"message": {"content": "Pass dependencies to their consumers."}, "done": True}
        )

    response = request_chat({"question": "  Explain dependency injection.  "}, ollama)
    assert response.status_code == 200
    assert response.json() == {"answer": "Pass dependencies to their consumers."}


@pytest.mark.parametrize(
    "body",
    [{}, {"question": ""}, {"question": " \n "}, {"question": None},
     {"question": 123}, {"question": "x" * 10001}],
)
def test_invalid_question_does_not_call_ollama(body: object) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach Ollama")

    assert request_chat(body, unexpected).status_code == 422


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (httpx.ConnectError, 503, "Make sure Ollama is running"),
        (httpx.ConnectTimeout, 504, "timed out"),
        (httpx.ReadTimeout, 504, "timed out"),
        (httpx.ReadError, 502, "Communication with Ollama failed"),
    ],
)
def test_ollama_transport_errors(
    error: type[httpx.RequestError], status: int, detail: str
) -> None:
    def ollama(request: httpx.Request) -> httpx.Response:
        raise error("private upstream details", request=request)

    response = request_chat({"question": "Hello"}, ollama)
    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert "private upstream details" not in response.text


@pytest.mark.parametrize("status", [404, 429, 500, 302])
def test_ollama_http_errors(status: int) -> None:
    response = request_chat(
        {"question": "Hello"},
        lambda request: httpx.Response(status, json={"error": "private upstream details"}),
    )
    assert response.status_code == 502
    assert "private upstream details" not in response.text
    if status == 404:
        assert "OLLAMA_MODEL" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": {"content": None}, "done": True},
        {"message": {"content": ""}, "done": True},
        {"message": {"content": "  "}, "done": True},
        {"message": {"content": "partial"}, "done": False},
        {"message": {"content": "partial"}},
    ],
)
def test_unusable_ollama_response(payload: object) -> None:
    response = request_chat(
        {"question": "Hello"}, lambda request: httpx.Response(200, json=payload)
    )
    assert response.status_code == 502


def test_ollama_invalid_json() -> None:
    response = request_chat(
        {"question": "Hello"}, lambda request: httpx.Response(200, content=b"not JSON")
    )
    assert response.status_code == 502


def test_provider_dependency_uses_application_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check production dependency wiring, including URL, timeout, and cleanup."""
    from starlette.requests import Request

    application = create_app()
    application.state.settings = Settings(
        _env_file=None,
        ollama_base_url="http://lan-host:11434",
        ollama_model="configured-model",
        ollama_timeout_seconds=17,
    )
    real_client = httpx.AsyncClient
    clients: list[httpx.AsyncClient] = []

    def ollama(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://lan-host:11434/api/chat"
        assert json.loads(request.content)["model"] == "configured-model"
        assert request.extensions["timeout"]["read"] == 17
        return httpx.Response(200, json={"message": {"content": "Hello"}, "done": True})

    def client_factory(*, base_url: str, timeout: float) -> httpx.AsyncClient:
        client = real_client(
            base_url=base_url, timeout=timeout, transport=httpx.MockTransport(ollama)
        )
        clients.append(client)
        return client

    monkeypatch.setattr("app.api.chat.httpx.AsyncClient", client_factory)

    async def generate() -> None:
        request = Request({"type": "http", "app": application})
        async for provider in get_llm_provider(request):
            assert await provider.generate("Hello") == "Hello"

    asyncio.run(generate())
    assert len(clients) == 1
    assert clients[0].is_closed
