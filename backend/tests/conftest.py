"""Isolated database built by the real migration chain, with no live services."""

from collections.abc import Iterator
import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    migrations = []
    for path in sorted((Path(__file__).resolve().parents[1] / "migrations/versions").glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migrations.append(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for migration in migrations:
                migration.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    yield engine
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for migration in reversed(migrations):
                migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()
