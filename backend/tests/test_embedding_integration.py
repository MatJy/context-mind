"""Opt-in verification against local PostgreSQL/pgvector and an Ollama model."""

import os
from math import isfinite
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.api.repositories import get_embedding_provider
from app.core.config import Settings
from app.main import create_app
from app.models import CodeChunk, Repository
from app.services.embeddings import EmbeddingUnavailableError


@pytest.mark.skipif(
    os.getenv("RUN_LOCAL_EMBEDDING_INTEGRATION") != "1",
    reason="Set RUN_LOCAL_EMBEDDING_INTEGRATION=1 after configuring PostgreSQL and Ollama",
)
def test_real_index_reuses_vectors_and_keeps_snapshot_on_failure(tmp_path: Path) -> None:
    settings = Settings()
    assert settings.database_url is not None
    engine = create_engine(settings.database_url.get_secret_value(), connect_args={"connect_timeout": 5})
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    file = tmp_path / "example.py"
    original = "def greet(name):\n    return 'Hello ' + name\n"
    file.write_text(original, encoding="utf-8", newline="")
    (tmp_path / ".env").write_text("DUMMY_SECRET=never-embed-this", encoding="utf-8")
    repository_path = str(tmp_path.resolve())
    app = create_app()
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        with TestClient(app) as client:
            first = client.post("/api/repositories/index", json={"path": str(tmp_path)})
            assert first.status_code == 200, first.json().get("detail")
            body = first.json()
            assert (body["embedded_chunk_count"], body["reused_chunk_count"]) == (1, 0)
            search = client.post(
                f"/api/repositories/{body['id']}/search",
                json={"question": "How does greet build a greeting?", "top_k": 2},
            )
            assert search.status_code == 200, search.json().get("detail")
            matches = search.json()["matches"]
            assert len(matches) == 1
            assert matches[0]["file_path"] == "example.py" and matches[0]["content"] == original
            assert (matches[0]["start_line"], matches[0]["end_line"]) == (1, 2)
            assert -1 <= matches[0]["similarity"] <= 1
            with Session(engine) as session:
                stored = session.scalar(select(CodeChunk).where(CodeChunk.repository_id == body["id"]))
                assert stored is not None
                assert stored.content == original and stored.file_path == "example.py"
                assert stored.embedding is not None
                assert len(stored.embedding) == settings.embedding_dimensions
                assert all(isfinite(value) for value in stored.embedding)
                before = list(stored.embedding)
            second = client.post("/api/repositories/index", json={"path": str(tmp_path)})
            assert second.status_code == 200
            assert second.json()["id"] == body["id"]
            assert (second.json()["embedded_chunk_count"], second.json()["reused_chunk_count"]) == (0, 1)
            with Session(engine) as session:
                stored = session.scalar(select(CodeChunk).where(CodeChunk.repository_id == body["id"]))
                assert stored is not None and list(stored.embedding) == before

            class OfflineProvider:
                model = settings.embedding_model
                dimensions = settings.embedding_dimensions
                cache_key = "f" * 64

                def embed(self, texts: list[str]) -> list[list[float]]:
                    raise EmbeddingUnavailableError("Simulated local model offline")

                def embed_query(self, question: str) -> list[float]:
                    raise EmbeddingUnavailableError("Simulated local model offline")

            file.write_text("print('changed')\n", encoding="utf-8")
            app.dependency_overrides[get_embedding_provider] = OfflineProvider
            failed = client.post("/api/repositories/index", json={"path": str(tmp_path)})
            assert failed.status_code == 503
            app.dependency_overrides.clear()
            with Session(engine) as session:
                assert session.scalar(select(CodeChunk.content).where(CodeChunk.repository_id == body["id"])) == original
            changed = client.post("/api/repositories/index", json={"path": str(tmp_path)})
            assert changed.status_code == 200
            assert (changed.json()["embedded_chunk_count"], changed.json()["reused_chunk_count"]) == (1, 0)
            file.unlink()
            empty = client.post("/api/repositories/index", json={"path": str(tmp_path)})
            assert empty.status_code == 200 and empty.json()["chunk_count"] == 0
    finally:
        # Only remove the disposable repository created by this test.
        with engine.begin() as connection:
            connection.execute(delete(Repository).where(Repository.path == repository_path))
        engine.dispose()


@pytest.mark.skipif(
    os.getenv("RUN_LOCAL_EMBEDDING_INTEGRATION") != "1",
    reason="Set RUN_LOCAL_EMBEDDING_INTEGRATION=1 after configuring PostgreSQL",
)
def test_real_pgvector_ranking_limits_and_repository_isolation(tmp_path: Path) -> None:
    """Known vectors prove ranking independently of language-model quality."""
    from app.schemas.chunk import CodeChunk as SourceChunk
    from app.services.persistence import persist_repository
    from app.services.retrieval import retrieve_chunks

    class KnownProvider:
        model = "deterministic-test"
        dimensions = 3
        cache_key = "a" * 64

        def embed(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("Only question embedding is expected")

        def embed_query(self, question: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    settings = Settings()
    assert settings.database_url is not None
    engine = create_engine(settings.database_url.get_secret_value(), connect_args={"connect_timeout": 5})
    paths = [str(tmp_path / name) for name in ("target", "other", "different-dimensions")]

    def chunk(path: str) -> SourceChunk:
        return SourceChunk(file_path=path, content=f"source {path}\n", start_line=2, end_line=3)

    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = persist_repository(
                session, paths[0], [chunk("opposite.py"), chunk("orthogonal.py"), chunk("best.py")],
                embeddings=[[-1, 0, 0], [0, 1, 0], [1, 0, 0]],
                embedding_model=KnownProvider.model, embedding_key=KnownProvider.cache_key,
            )
            persist_repository(
                session, paths[1], [chunk("other.py")], embeddings=[[1, 0, 0]],
                embedding_model=KnownProvider.model, embedding_key=KnownProvider.cache_key,
            )
            persist_repository(
                session, paths[2], [chunk("different.py")], embeddings=[[1, 0]],
                embedding_model="other-model", embedding_key="b" * 64,
            )
            matches = retrieve_chunks(session, repository.id, "question", KnownProvider(), 2)
            assert [match.file_path for match in matches] == ["best.py", "orthogonal.py"]
            assert [match.similarity for match in matches] == pytest.approx([1.0, 0.0])
            all_matches = retrieve_chunks(session, repository.id, "question", KnownProvider(), 5)
            assert len(all_matches) == 3
            assert all_matches[-1].similarity == pytest.approx(-1.0)
            assert all_matches[0].content == "source best.py\n"
            assert (all_matches[0].start_line, all_matches[0].end_line) == (2, 3)
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Repository).where(Repository.path.in_(paths)))
        engine.dispose()
