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
