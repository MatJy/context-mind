"""LLM settings validation and environment overrides."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LLM_PROVIDER", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT_SECONDS", "DATABASE_URL",
        "EMBEDDING_PROVIDER", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS",
        "EMBEDDING_BATCH_SIZE", "EMBEDDING_TIMEOUT_SECONDS", "RETRIEVAL_TOP_K",
    ):
        monkeypatch.delenv(name, raising=False)


def test_local_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert str(settings.ollama_base_url) == "http://localhost:11434/"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.ollama_timeout_seconds == 120.0
    assert settings.embedding_provider == "local"
    assert str(settings.embedding_base_url) == "http://localhost:11434/"
    assert settings.embedding_model == "nomic-embed-text:v1.5"
    assert settings.embedding_dimensions == 768
    assert settings.embedding_batch_size == 16
    assert settings.embedding_timeout_seconds == 120.0
    assert settings.retrieval_top_k == 5


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.10:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "another-model:latest")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "30")
    settings = Settings(_env_file=None)
    assert str(settings.ollama_base_url) == "http://192.168.1.10:11434/"
    assert settings.ollama_model == "another-model:latest"
    assert settings.ollama_timeout_seconds == 30.0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LLM_PROVIDER", "openai"),
        ("OLLAMA_BASE_URL", "not-a-url"),
        ("OLLAMA_BASE_URL", "ftp://localhost"),
        ("OLLAMA_MODEL", "   "),
        ("OLLAMA_TIMEOUT_SECONDS", "0"),
        ("OLLAMA_TIMEOUT_SECONDS", "-1"),
        ("OLLAMA_TIMEOUT_SECONDS", "nan"),
        ("OLLAMA_TIMEOUT_SECONDS", "inf"),
        ("DATABASE_URL", "not-a-url"),
        ("DATABASE_URL", "sqlite:///local.db"),
        ("DATABASE_URL", "postgresql+psycopg://localhost"),
        ("EMBEDDING_PROVIDER", "openai"),
        ("EMBEDDING_BASE_URL", "not-a-url"),
        ("EMBEDDING_MODEL", "   "),
        ("EMBEDDING_DIMENSIONS", "0"),
        ("EMBEDDING_DIMENSIONS", "2001"),
        ("EMBEDDING_BATCH_SIZE", "0"),
        ("EMBEDDING_BATCH_SIZE", "129"),
        ("EMBEDDING_TIMEOUT_SECONDS", "0"),
        ("EMBEDDING_TIMEOUT_SECONDS", "nan"),
        ("EMBEDDING_TIMEOUT_SECONDS", "inf"),
        ("RETRIEVAL_TOP_K", "0"),
        ("RETRIEVAL_TOP_K", "21"),
    ],
)
def test_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_is_optional_and_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).database_url is None
    url = "postgresql+psycopg://user:dummy-password@localhost/context_mind"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == url
    assert "dummy-password" not in repr(settings)


def test_embedding_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://192.168.1.10:11434")
    monkeypatch.setenv("EMBEDDING_MODEL", "another-local-model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "384")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "8")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "3")
    settings = Settings(_env_file=None)
    assert str(settings.embedding_base_url) == "http://192.168.1.10:11434/"
    assert settings.embedding_model == "another-local-model"
    assert settings.embedding_dimensions == 384
    assert settings.embedding_batch_size == 8
    assert settings.embedding_timeout_seconds == 60
    assert settings.retrieval_top_k == 3
