"""Embedding HTTP contract, batching, cache invalidation, and atomic failures."""

from collections.abc import Iterator
import json

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api import repositories as routes
from app.core.database import get_session
from app.main import create_app
from app.models import CodeChunk, Repository
from app.schemas.chunk import ChunkingOptions, CodeChunk as SourceChunk, RepositoryChunkResponse
from app.services.embeddings import (
    EmbeddingResponseError, EmbeddingTimeoutError, EmbeddingUnavailableError,
    validate_embeddings,
)
from app.services.indexing import index_repository
from app.services.local_embeddings import LocalEmbeddingProvider
from app.services.persistence import persist_repository


class FakeProvider:
    model = "test-model"
    dimensions = 3
    cache_key = "a" * 64

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(text)), 1.0, 0.0] for text in texts]

    def embed_query(self, question: str) -> list[float]:
        return self.embed([question])[0]


def source(content: str, path: str = "main.py") -> SourceChunk:
    return SourceChunk(file_path=path, content=content, start_line=1, end_line=1)


def test_local_http_batch_and_document_prefix() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [[1, 2, 3], [4, 5, 6]]})

    with httpx.Client(base_url="http://localhost:11434/", transport=httpx.MockTransport(respond)) as client:
        provider = LocalEmbeddingProvider(client, "nomic-embed-text:v1.5", 3)
        assert provider.embed(["first", "second"]) == [[1, 2, 3], [4, 5, 6]]
        assert provider.embed([]) == []
    assert len(requests) == 1
    assert requests[0].url.path == "/api/embed"
    assert json.loads(requests[0].content) == {
        "model": "nomic-embed-text:v1.5",
        "input": ["search_document: first", "search_document: second"], "truncate": False,
    }


def test_cache_identity_tracks_model_host_dimensions_and_prefix() -> None:
    with httpx.Client(base_url="http://localhost:11434/") as first, httpx.Client(base_url="http://127.0.0.1:11434/") as second:
        original = LocalEmbeddingProvider(first, "nomic-embed-text:v1.5", 768)
        keys = {
            original.cache_key,
            LocalEmbeddingProvider(first, "different-model", 768).cache_key,
            LocalEmbeddingProvider(second, "nomic-embed-text:v1.5", 768).cache_key,
            LocalEmbeddingProvider(first, "nomic-embed-text:v1.5", 512).cache_key,
        }
        assert len(keys) == 4
        original.document_prefix = "changed-prefix: "
        assert original.cache_key not in keys


@pytest.mark.parametrize("error, expected", [
    (httpx.ConnectError, EmbeddingUnavailableError),
    (httpx.ReadTimeout, EmbeddingTimeoutError),
    (httpx.RemoteProtocolError, EmbeddingResponseError),
])
def test_transport_errors_are_safe(error, expected) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error("private upstream details")

    with httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(expected) as caught:
            LocalEmbeddingProvider(client, "model", 3).embed(["code"])
        assert "private" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 404, 413, 500])
def test_upstream_http_errors_do_not_echo_source_text(status: int) -> None:
    with httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text="private source text"),
    )) as client:
        with pytest.raises(EmbeddingResponseError) as caught:
            LocalEmbeddingProvider(client, "model", 3).embed(["code"])
        assert "private" not in str(caught.value)


@pytest.mark.parametrize("value", [
    None, {}, [], [[1.0, 2.0]], [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]],
    [[float("nan"), 1.0, 2.0]], [[float("inf"), 1.0, 2.0]],
    [[True, 1.0, 2.0]], [["1", 1.0, 2.0]], [[0.0, 0.0, 0.0]],
    [[1e100, 1.0, 0.0]], [[1e-100, 0.0, 0.0]],
])
def test_invalid_vectors_are_rejected(value: object) -> None:
    with pytest.raises(EmbeddingResponseError):
        validate_embeddings(value, 1, 3)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"{}", b'{"embeddings": null}'])
def test_malformed_http_response(body: bytes) -> None:
    with httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=body),
    )) as client:
        with pytest.raises(EmbeddingResponseError):
            LocalEmbeddingProvider(client, "model", 3).embed(["code"])


def test_batching_deduplication_and_unchanged_reuse(database: Engine) -> None:
    provider = FakeProvider()
    chunks = [source("one"), source("two"), source("three"), source("one", "copy.py")]
    with Session(database, expire_on_commit=False) as session:
        first = index_repository(session, "/repos/example", chunks, provider, batch_size=2)
        assert (first.embedded_chunk_count, first.reused_chunk_count) == (4, 0)
        assert provider.calls == [["one", "two"], ["three"]]
        provider.calls.clear()
        moved = [chunk.model_copy(update={"file_path": "moved/" + chunk.file_path}) for chunk in chunks]
        again = index_repository(session, "/repos/example", moved, provider, batch_size=2)
        assert again.repository.id == first.repository.id
        assert (again.embedded_chunk_count, again.reused_chunk_count) == (0, 4)
        assert provider.calls == []
    with Session(database) as session:
        stored = session.scalars(select(CodeChunk)).all()
        assert len(stored) == 4
        assert all(row.embedding is not None and len(row.embedding) == 3 for row in stored)
        assert all(row.file_path.startswith("moved/") for row in stored)


def test_changed_content_model_and_dimensions_invalidate_cache(database: Engine) -> None:
    provider = FakeProvider()
    with Session(database, expire_on_commit=False) as session:
        index_repository(session, "/repos/example", [source("old"), source("same")], provider, 16)
        provider.calls.clear()
        changed = index_repository(session, "/repos/example", [source("new"), source("same")], provider, 16)
        assert (changed.embedded_chunk_count, changed.reused_chunk_count) == (1, 1)
        assert provider.calls == [["new"]]
        provider.cache_key = "b" * 64
        provider.model = "new-model"
        provider.calls.clear()
        index_repository(session, "/repos/example", [source("new"), source("same")], provider, 16)
        assert provider.calls == [["new", "same"]]


def test_legacy_chunks_are_embedded_and_empty_repository_clears(database: Engine) -> None:
    provider = FakeProvider()
    with Session(database, expire_on_commit=False) as session:
        persist_repository(session, "/repos/example", [source("legacy")])
        result = index_repository(session, "/repos/example", [source("legacy")], provider, 16)
        assert result.embedded_chunk_count == 1
        assert provider.calls == [["legacy"]]
        provider.calls.clear()
        index_repository(session, "/repos/example", [], provider, 16)
        assert provider.calls == []
    with Session(database) as session:
        assert session.scalars(select(CodeChunk)).all() == []
        assert len(session.scalars(select(Repository)).all()) == 1


def test_partial_inference_failure_preserves_old_snapshot(database: Engine) -> None:
    class FailSecondBatch(FakeProvider):
        def embed(self, texts: list[str]) -> list[list[float]]:
            if self.calls:
                raise EmbeddingTimeoutError("timed out")
            return super().embed(texts)

    with Session(database, expire_on_commit=False) as session:
        original = index_repository(session, "/repos/example", [source("original")], FakeProvider(), 1)
        timestamp = original.repository.indexed_at
        with pytest.raises(EmbeddingTimeoutError):
            index_repository(session, "/repos/example", [source("new1"), source("new2")], FailSecondBatch(), 1)
    with Session(database) as session:
        assert session.scalar(select(CodeChunk.content)) == "original"
        saved = session.scalar(select(Repository))
        assert saved is not None
        assert saved.indexed_at.replace(tzinfo=timestamp.tzinfo) == timestamp


def test_invalid_provider_vectors_cannot_replace_snapshot(database: Engine) -> None:
    class InvalidProvider(FakeProvider):
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[float("nan"), 0.0, 0.0]]

    with Session(database, expire_on_commit=False) as session:
        persist_repository(session, "/repos/example", [source("original")])
        with pytest.raises(EmbeddingResponseError):
            index_repository(session, "/repos/example", [source("new")], InvalidProvider(), 16)
    with Session(database) as session:
        assert session.scalar(select(CodeChunk.content)) == "original"


@pytest.mark.parametrize("error, status", [
    (EmbeddingUnavailableError, 503), (EmbeddingTimeoutError, 504), (EmbeddingResponseError, 502),
])
def test_endpoint_maps_embedding_errors(database: Engine, monkeypatch, error, status: int) -> None:
    class BrokenProvider(FakeProvider):
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise error("Embedding failed safely")

    app = create_app()

    def session_override() -> Iterator[Session]:
        with Session(database, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[routes.get_embedding_provider] = BrokenProvider
    monkeypatch.setattr(routes, "chunks", lambda body: RepositoryChunkResponse(
        repository_path="/repos/example", chunks=[source("content")],
        chunking=ChunkingOptions(), skipped_files=[],
    ))
    with TestClient(app) as client:
        response = client.post("/api/repositories/index", json={"path": "/repos/example"})
    assert response.status_code == status
    with Session(database) as session:
        assert session.scalars(select(Repository)).all() == []
