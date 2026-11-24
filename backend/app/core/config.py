"""Typed configuration loaded from the environment and root .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings; environment variables override the .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "Context Mind API"
    database_url: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("DATABASE_URL must use postgresql+psycopg and name a database")
        return value

    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model: str = Field(default="llama3.2:3b", min_length=1, pattern=r"\S")
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)

    embedding_provider: Literal["local"] = "local"
    embedding_base_url: HttpUrl = HttpUrl("http://localhost:11434")
    embedding_model: str = Field(default="nomic-embed-text:v1.5", min_length=1, pattern=r"\S")
    embedding_dimensions: int = Field(default=768, ge=1, le=2000)
    embedding_batch_size: int = Field(default=16, ge=1, le=128)
    embedding_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    rag_max_context_characters: int = Field(default=24000, ge=1, le=200000)
