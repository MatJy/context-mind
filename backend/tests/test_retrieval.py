"""Query formatting, search contracts, vector-space guards, and PostgreSQL SQL."""

from collections.abc import Iterator
import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api import repositories as routes
from app.core.database import get_session
from app.main import create_app
from app.models import CodeChunk
from app.schemas.chunk import CodeChunk as SourceChunk
from app.schemas.retrieval import RetrievalMatch
from app.services.embeddings import EmbeddingResponseError, EmbeddingTimeoutError, EmbeddingUnavailableError
from app.services.local_embeddings import LocalEmbeddingProvider
from app.services.persistence import persist_repository
from app.services.retrieval import RepositoryNotFoundError, RetrievalIndexError, retrieve_chunks


class QueryProvider:
    model = "test-model"
    dimensions = 3
    cache_key = "a" * 64

    def __init__(self) -> None:
        self.questions: list[str] = []

    def embed_query(self, question: str) -> list[float]:
        self.questions.append(question)
        return [1.0, 0.0, 0.0]

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("Search must use query embeddings")


@pytest.mark.parametrize("model, prefix", [
    ("nomic-embed-text:v1.5", "search_query: "), ("another-model", ""),
])
def test_query_embedding_request_and_cache_identity(model: str, prefix: str) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[1, 0, 0]]})

    with httpx.Client(base_url="http://localhost:11434/", transport=httpx.MockTransport(respond)) as client:
        provider = LocalEmbeddingProvider(client, model, 3)
        key = provider.cache_key
        assert provider.embed_query("Where is scanning?") == [1, 0, 0]
        assert provider.cache_key == key
        assert provider.embed(["code"]) == [[1, 0, 0]]
    assert requests[0] == {
        "model": model, "input": [prefix + "Where is scanning?"], "truncate": False,
    }
    assert requests[1]["input"] == ["search_document: code" if prefix else "code"]


def test_pgvector_query_and_source_mapping() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = 7
    chunk = CodeChunk(file_path="src/main.py", content="exact source\n", start_line=12, end_line=14)
    session.execute.return_value.all.side_effect = [
        [(QueryProvider.cache_key, QueryProvider.model)], [(chunk, 0.25)],
    ]
    provider = QueryProvider()
    result = retrieve_chunks(session, 7, "question", provider, 3)
    assert result == [RetrievalMatch(
        file_path="src/main.py", content="exact source\n", start_line=12, end_line=14, similarity=0.75,
    )]
    assert provider.questions == ["question"]
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "embedding <=>" in sql
    assert "code_chunks.repository_id =" in sql and "code_chunks.embedding_key =" in sql
    assert "code_chunks.embedding_model =" in sql and "embedding IS NOT NULL" in sql
    assert "ORDER BY distance, code_chunks.file_path, code_chunks.start_line, code_chunks.id" in sql
    assert 7 in compiled.params.values() and 3 in compiled.params.values()
    lock = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR SHARE" in lock


def test_missing_empty_and_incompatible_repositories(database: Engine) -> None:
    provider = QueryProvider()
    with Session(database, expire_on_commit=False) as session:
        empty = persist_repository(session, "/repos/empty", [])
        legacy = persist_repository(session, "/repos/legacy", [
            SourceChunk(file_path="main.py", content="code", start_line=1, end_line=1),
        ])
        with pytest.raises(RepositoryNotFoundError):
            retrieve_chunks(session, 9999, "question", provider, 5)
        assert retrieve_chunks(session, empty.id, "question", provider, 5) == []
        with pytest.raises(RetrievalIndexError, match="Re-index"):
            retrieve_chunks(session, legacy.id, "question", provider, 5)
    assert provider.questions == []


@pytest.mark.parametrize("metadata", [
    [("different-host-or-dimensions", QueryProvider.model)],
    [(QueryProvider.cache_key, "different-model")],
    [(QueryProvider.cache_key, QueryProvider.model), (None, None)],
])
def test_incompatible_metadata_prevents_inference(metadata) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = 1
    session.execute.return_value.all.return_value = metadata
    provider = QueryProvider()
    with pytest.raises(RetrievalIndexError):
        retrieve_chunks(session, 1, "question", provider, 5)
    assert provider.questions == []


@pytest.mark.parametrize("vector", [[0, 0, 0], [1, 0], [float("nan"), 0, 0]])
def test_invalid_query_vector_is_rejected(vector) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = 1
    session.execute.return_value.all.return_value = [(QueryProvider.cache_key, QueryProvider.model)]
    provider = MagicMock(spec=QueryProvider)
    provider.cache_key, provider.model, provider.dimensions = QueryProvider.cache_key, QueryProvider.model, 3
    provider.embed_query.return_value = vector
    with pytest.raises(EmbeddingResponseError):
        retrieve_chunks(session, 1, "question", provider, 5)
    assert session.execute.call_count == 1


@pytest.fixture
def search_app(database: Engine):
    app = create_app()

    def session_override() -> Iterator[Session]:
        with Session(database) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[routes.get_embedding_provider] = QueryProvider
    return app


@pytest.mark.parametrize("top_k", [None, 2])
def test_search_endpoint_defaults_override_and_response(search_app, monkeypatch, top_k) -> None:
    search_app.state.settings.retrieval_top_k = 4
    retrieval = MagicMock(return_value=[RetrievalMatch(
        file_path="src/auth.py", start_line=5, end_line=8, content="source", similarity=0.9,
    )])
    monkeypatch.setattr(routes, "retrieve_chunks", retrieval)
    body = {"question": "  How does auth work?  "}
    if top_k is not None:
        body["top_k"] = top_k
    with TestClient(search_app) as client:
        response = client.post("/api/repositories/1/search", json=body)
    assert response.status_code == 200
    result = response.json()
    assert result["question"] == "How does auth work?"
    assert result["top_k"] == (top_k or 4)
    assert result["repository_id"] == 1
    assert result["matches"][0] == {
        "file_path": "src/auth.py", "start_line": 5, "end_line": 8, "content": "source", "similarity": 0.9,
    }
    assert retrieval.call_args.args[2] == "How does auth work?"
    assert retrieval.call_args.args[4] == (top_k or 4)


@pytest.mark.parametrize("body", [
    {}, {"question": "   "}, {"question": "x" * 8001}, {"question": 123},
    *[{"question": "valid", "top_k": value} for value in [0, -1, 21, True, 2.5, "3"]],
])
def test_invalid_search_requests(search_app, monkeypatch, body) -> None:
    retrieval = MagicMock()
    monkeypatch.setattr(routes, "retrieve_chunks", retrieval)
    with TestClient(search_app) as client:
        assert client.post("/api/repositories/1/search", json=body).status_code == 422
    retrieval.assert_not_called()


@pytest.mark.parametrize("error, status", [
    (RepositoryNotFoundError, 404), (RetrievalIndexError, 409),
    (EmbeddingUnavailableError, 503), (EmbeddingTimeoutError, 504), (EmbeddingResponseError, 502),
])
def test_search_error_mapping(search_app, monkeypatch, error, status: int) -> None:
    monkeypatch.setattr(routes, "retrieve_chunks", MagicMock(side_effect=error("Safe guidance")))
    with TestClient(search_app) as client:
        response = client.post("/api/repositories/1/search", json={"question": "question"})
    assert response.status_code == status
    assert response.json()["detail"] == "Safe guidance"


def test_search_without_database_configuration(monkeypatch) -> None:
    app = create_app()
    app.state.settings.database_url = None
    with TestClient(app) as client:
        response = client.post("/api/repositories/1/search", json={"question": "question"})
    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]
