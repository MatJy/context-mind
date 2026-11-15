"""Read the database URL from application configuration, never from source control."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import Settings
from app.models import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    url = Settings().database_url
    if url is None:
        raise RuntimeError("Set DATABASE_URL before running migrations.")
    if context.is_offline_mode():
        context.configure(
            url=url.get_secret_value(), target_metadata=target_metadata,
            literal_binds=True, dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(
        url.get_secret_value(), poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
