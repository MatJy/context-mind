"""Ollama's non-streaming chat HTTP integration."""

import httpx
from pydantic import BaseModel, ValidationError

from app.services.llm import LLMResponseError, LLMTimeoutError, LLMUnavailableError


class _Message(BaseModel):
    content: str


class _ChatResult(BaseModel):
    message: _Message
    done: bool


class OllamaProvider:
    """Keep Ollama's HTTP format and errors behind the provider interface."""

    def __init__(self, client: httpx.AsyncClient, model: str) -> None:
        self.client = client
        self.model = model

    async def generate(self, question: str) -> str:
        """Request one complete answer without streaming or conversation history."""
        try:
            response = await self.client.post(
                "api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": question}],
                    "stream": False,
                },
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                "Ollama timed out. Try again or increase OLLAMA_TIMEOUT_SECONDS."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                "Cannot connect to Ollama. Make sure Ollama is running and "
                "OLLAMA_BASE_URL points to the correct host."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMResponseError("Communication with Ollama failed. Try again.") from exc

        if response.status_code == 404:
            raise LLMResponseError(
                "Ollama model or endpoint was not found. Check OLLAMA_BASE_URL "
                "and pull the model configured in OLLAMA_MODEL."
            )
        if not response.is_success:
            raise LLMResponseError("Ollama returned an unsuccessful response. Check its logs.")
        try:
            result = _ChatResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise LLMResponseError("Ollama returned an invalid chat response.") from exc
        if not result.done or not result.message.content.strip():
            raise LLMResponseError("Ollama returned an incomplete or empty answer.")
        return result.message.content
