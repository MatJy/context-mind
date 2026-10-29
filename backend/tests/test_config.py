"""LLM settings validation and environment overrides."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LLM_PROVIDER", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT_SECONDS"
    ):
        monkeypatch.delenv(name, raising=False)


def test_local_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert str(settings.ollama_base_url) == "http://localhost:11434/"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.ollama_timeout_seconds == 120.0


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
    ],
)
def test_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
