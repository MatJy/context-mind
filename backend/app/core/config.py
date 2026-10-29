"""Typed configuration loaded from the environment and root .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model: str = Field(default="llama3.2:3b", min_length=1, pattern=r"\S")
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)
