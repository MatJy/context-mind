"""Repository chat combines synchronous retrieval and asynchronous generation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from app.api.chat import get_llm_provider
from app.api.repositories import get_embedding_provider
from app.core.database import get_session
from app.schemas.rag import RAGRequest, RAGResponse
from app.schemas.retrieval import RetrievalMatch
from app.services.embeddings import (
    EmbeddingProvider, EmbeddingResponseError, EmbeddingTimeoutError, EmbeddingUnavailableError,
)
from app.services.llm import LLMProvider, LLMResponseError, LLMTimeoutError, LLMUnavailableError
from app.services.rag import generate_answer
from app.services.retrieval import RepositoryNotFoundError, RetrievalIndexError, retrieve_chunks

router = APIRouter()


def get_context(
    repository_id: Annotated[int, Path(ge=1)],
    body: RAGRequest,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    request: Request,
) -> list[RetrievalMatch]:
    """Run blocking work in a worker and release the snapshot lock before LLM I/O."""
    top_k = body.top_k if body.top_k is not None else request.app.state.settings.retrieval_top_k
    try:
        with session.begin():
            return retrieve_chunks(session, repository_id, body.question, provider, top_k)
    except RepositoryNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    except RetrievalIndexError as exc:
        raise HTTPException(409, str(exc)) from None
    except EmbeddingUnavailableError as exc:
        raise HTTPException(503, str(exc)) from None
    except EmbeddingTimeoutError as exc:
        raise HTTPException(504, str(exc)) from None
    except EmbeddingResponseError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post(
    "/repositories/{repository_id}/chat", response_model=RAGResponse, tags=["repositories"],
)
async def chat(
    repository_id: Annotated[int, Path(ge=1)],
    body: RAGRequest,
    matches: Annotated[list[RetrievalMatch], Depends(get_context)],
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    request: Request,
) -> RAGResponse:
    """Answer from the last indexed snapshot and return the prompt's sources."""
    try:
        return await generate_answer(
            repository_id, body.question, matches, provider,
            request.app.state.settings.rag_max_context_characters,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(503, str(exc)) from None
    except LLMTimeoutError as exc:
        raise HTTPException(504, str(exc)) from None
    except LLMResponseError as exc:
        raise HTTPException(502, str(exc)) from None
