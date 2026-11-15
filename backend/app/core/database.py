"""Database lifecycle and request-scoped synchronous sessions."""

from collections.abc import Iterator
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@asynccontextmanager
async def database_lifespan(app: FastAPI) -> AsyncIterator[None]:
    url = app.state.settings.database_url
    engine = None
    app.state.session_factory = None
    if url is not None:
        engine = create_engine(
            url.get_secret_value(), pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
        app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        if engine is not None:
            engine.dispose()


def get_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(503, "Configure DATABASE_URL and restart the backend to enable persistence.")
    try:
        with factory() as session:
            yield session
    except IntegrityError:
        raise HTTPException(409, "Indexing conflicted with another update. Retry the request.") from None
    except SQLAlchemyError:
        # Database exception messages can contain credentials and source text.
        raise HTTPException(
            503, "Database operation failed. Check PostgreSQL, DATABASE_URL, and run migrations."
        ) from None
