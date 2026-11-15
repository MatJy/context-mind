"""Local repository ingestion endpoint."""

from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.schemas.indexing import RepositoryIndexResponse
from app.services.embeddings import (
    EmbeddingProvider, EmbeddingResponseError, EmbeddingTimeoutError, EmbeddingUnavailableError,
)
from app.services.indexing import index_repository
from app.services.local_embeddings import LocalEmbeddingProvider

from app.schemas.chunk import RepositoryChunkRequest, RepositoryChunkResponse
from app.schemas.repository import RepositoryScanRequest, RepositoryScanResponse
from app.services.chunking import ChunkingLimitError, chunk_files
from app.services.repository import (
    GitTimeoutError, GitUnavailableError, RepositoryLimitError,
    RepositoryScanError, scan_repository,
)

router = APIRouter()


def get_embedding_provider(request: Request) -> Iterator[EmbeddingProvider]:
    settings = request.app.state.settings
    with httpx.Client(
        base_url=str(settings.embedding_base_url), timeout=settings.embedding_timeout_seconds,
        trust_env=False,
    ) as client:
        yield LocalEmbeddingProvider(client, settings.embedding_model, settings.embedding_dimensions)


@router.post("/repositories/scan", response_model=RepositoryScanResponse, tags=["repositories"])
def scan(body: RepositoryScanRequest) -> RepositoryScanResponse:
    """Scan on FastAPI's worker thread so filesystem work doesn't block async chat."""
    return _scan_repository(body.path)


def _scan_repository(path: str) -> RepositoryScanResponse:
    """Use the same scanner and error mapping for both repository endpoints."""
    try:
        return scan_repository(path)
    except GitUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GitTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RepositoryLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except RepositoryScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/repositories/chunks", response_model=RepositoryChunkResponse, tags=["repositories"]
)
def chunks(body: RepositoryChunkRequest) -> RepositoryChunkResponse:
    """Scan safely and return overlapping source windows without persisting them."""
    result = _scan_repository(body.path)
    try:
        code_chunks = chunk_files(result.files, body.chunking)
    except ChunkingLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return RepositoryChunkResponse(
        repository_path=result.repository_path,
        chunking=body.chunking,
        chunks=code_chunks,
        skipped_files=result.skipped_files,
    )


@router.post(
    "/repositories/index", response_model=RepositoryIndexResponse, tags=["repositories"]
)
def index(
    body: RepositoryChunkRequest,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    request: Request,
) -> RepositoryIndexResponse:
    """Scan and chunk safely, then atomically save the repository snapshot."""
    result = chunks(body)
    try:
        indexed = index_repository(
            session, result.repository_path, result.chunks, provider,
            request.app.state.settings.embedding_batch_size,
        )
    except EmbeddingUnavailableError as exc:
        raise HTTPException(503, str(exc)) from None
    except EmbeddingTimeoutError as exc:
        raise HTTPException(504, str(exc)) from None
    except EmbeddingResponseError as exc:
        raise HTTPException(502, str(exc)) from None
    repository = indexed.repository
    return RepositoryIndexResponse(
        id=repository.id, name=repository.name, path=repository.path,
        indexed_at=repository.indexed_at, chunk_count=len(result.chunks),
        embedding_model=provider.model,
        embedded_chunk_count=indexed.embedded_chunk_count,
        reused_chunk_count=indexed.reused_chunk_count,
        skipped_files=result.skipped_files,
    )
