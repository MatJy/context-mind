"""Small provider contract independent of any LLM vendor."""

from typing import Protocol


class LLMProvider(Protocol):
    """Generate a complete answer to a single question."""

    async def generate(self, question: str) -> str: ...


class LLMUnavailableError(Exception):
    """The configured LLM service cannot be reached."""


class LLMTimeoutError(Exception):
    """The configured LLM service did not respond in time."""


class LLMResponseError(Exception):
    """The configured LLM service returned an unusable response."""
