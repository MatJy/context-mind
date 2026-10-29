"""Single-question chat endpoint and provider dependency."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import Settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm import (
    LLMProvider,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.ollama import OllamaProvider

router = APIRouter()


async def get_llm_provider(request: Request) -> AsyncIterator[LLMProvider]:
    """Close the request's HTTP client even if generation fails."""
    settings: Settings = request.app.state.settings
    async with httpx.AsyncClient(
        base_url=str(settings.ollama_base_url),
        timeout=settings.ollama_timeout_seconds,
    ) as client:
        yield OllamaProvider(client, settings.ollama_model)


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    body: ChatRequest,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ChatResponse:
    """Generate a plain LLM answer; repository context is added in later phases."""
    try:
        answer = await provider.generate(body.question)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except LLMResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(answer=answer)
