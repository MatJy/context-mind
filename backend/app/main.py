"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import Settings


def create_app() -> FastAPI:
    """Create an application with validated settings and API routes."""
    settings = Settings()
    application = FastAPI(title=settings.app_name)
    application.state.settings = settings
    application.include_router(health_router, prefix="/api")
    application.include_router(chat_router, prefix="/api")
    return application


app = create_app()
