"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.repositories import router as repositories_router
from app.api.rag import router as rag_router
from app.core.config import Settings
from app.core.database import database_lifespan


def create_app() -> FastAPI:
    """Create an application with validated settings and API routes."""
    settings = Settings()
    application = FastAPI(title=settings.app_name, lifespan=database_lifespan)
    application.state.settings = settings
    application.include_router(health_router, prefix="/api")
    application.include_router(chat_router, prefix="/api")
    application.include_router(repositories_router, prefix="/api")
    application.include_router(rag_router, prefix="/api")
    return application


app = create_app()
