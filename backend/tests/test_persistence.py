"""Database transactions, migration schema, and safe indexing API behavior."""

from hashlib import sha256
from io import StringIO
from pathlib import Path
import subprocess

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.config import Settings
from app.main import create_app
from app.models import CodeChunk, Repository
from app.api.repositories import get_embedding_provider
from app.schemas.chunk import CodeChunk as SourceChunk
from app.services.persistence import persist_repository


def test_migration_generates_postgresql_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/context_mind")
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE repositories" in sql
    assert "CREATE TABLE code_chunks" in sql
    assert "SERIAL" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE CASCADE" in sql
    assert "CREATE INDEX ix_code_chunks_repository_id" in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "ADD COLUMN embedding VECTOR" in sql


def chunk(text: str = "print('héllo')\n") -> SourceChunk:
    return SourceChunk(file_path="src/main.py", content=text, start_line=1, end_line=1)


def test_snapshot_survives_new_session_and_reindex_replaces_chunks(database) -> None:
    with Session(database, expire_on_commit=False) as session:
        saved = persist_repository(session, "/repos/example", [chunk()])
        repository_id = saved.id
        timestamp = saved.indexed_at
    with Session(database, expire_on_commit=False) as session:
        row = session.scalar(select(CodeChunk))
        assert row is not None
        assert row.repository_id == repository_id
        assert (row.file_path, row.start_line, row.end_line, row.content) == (
            "src/main.py", 1, 1, chunk().content,
        )
        assert row.content_hash == sha256(chunk().content.encode("utf-8")).hexdigest()
        session.rollback()
        saved = persist_repository(session, "/repos/example", [chunk("changed")])
        assert saved.id == repository_id
        assert saved.name == "example"
        assert saved.indexed_at >= timestamp
    with Session(database, expire_on_commit=False) as session:
        assert [row.content for row in session.scalars(select(CodeChunk))] == ["changed"]
        session.rollback()
        persist_repository(session, "/repos/example", [])
    with Session(database) as session:
        assert session.scalars(select(CodeChunk)).all() == []
        assert len(session.scalars(select(Repository)).all()) == 1


def test_failed_replacement_rolls_back_entire_snapshot(database) -> None:
    with Session(database, expire_on_commit=False) as session:
        saved = persist_repository(session, "/repos/example", [chunk()])
        timestamp = saved.indexed_at
        invalid = chunk("new")
        invalid.end_line = 0
        with pytest.raises(IntegrityError):
            persist_repository(session, "/repos/example", [invalid])
    with Session(database) as session:
        assert session.scalar(select(CodeChunk.content)) == chunk().content
        stored = session.scalar(select(Repository))
        assert stored is not None
        assert stored.indexed_at.replace(tzinfo=timestamp.tzinfo) == timestamp


def test_repository_isolation_and_cascade(database) -> None:
    with Session(database, expire_on_commit=False) as session:
        first = persist_repository(session, "/repos/first", [chunk("first")])
        persist_repository(session, "/repos/second", [chunk("second")])
        with session.begin():
            session.delete(first)
    with Session(database) as session:
        assert [row.content for row in session.scalars(select(CodeChunk))] == ["second"]


def test_index_endpoint_uses_scanner_and_persists(database, tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "main.py").write_text("print('safe')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=dummy-secret", encoding="utf-8")
    app = create_app()

    def session_override():
        with Session(database, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    class FakeEmbeddings:
        model = "test-model"
        dimensions = 2
        cache_key = "a" * 64

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    app.dependency_overrides[get_embedding_provider] = FakeEmbeddings
    with TestClient(app) as client:
        response = client.post("/api/repositories/index", json={"path": str(tmp_path)})
        assert response.status_code == 200
        body = response.json()
        assert body["chunk_count"] == 1
        assert body["indexed_at"].endswith("Z")
        assert "dummy-secret" not in response.text
        (tmp_path / "main.py").unlink()
        again = client.post("/api/repositories/index", json={"path": str(tmp_path)})
        assert again.json()["id"] == body["id"]
        assert again.json()["chunk_count"] == 0
    with Session(database) as session:
        assert session.scalars(select(CodeChunk)).all() == []


def test_missing_database_does_not_break_health(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setattr("app.main.Settings", lambda: Settings(_env_file=None))
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        response = client.post("/api/repositories/index", json={"path": "/unused"})
        assert response.status_code == 503
        assert "DATABASE_URL" in response.json()["detail"]


@pytest.mark.parametrize("error, status", [(OperationalError, 503), (IntegrityError, 409)])
def test_database_errors_do_not_leak_sql_or_credentials(monkeypatch, error, status) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    class BrokenFactory:
        def __call__(self):
            raise error("source and password must stay private", {}, Exception("secret"))

    with TestClient(create_app()) as client:
        client.app.state.session_factory = BrokenFactory()
        response = client.post("/api/repositories/index", json={"path": "/unused"})
        assert response.status_code == status
        assert "private" not in response.text
        assert "secret" not in response.text
