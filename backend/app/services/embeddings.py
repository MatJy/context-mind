"""Small embedding contract and validation shared by provider implementations."""

from typing import Annotated, Protocol

from pydantic import Field, TypeAdapter, ValidationError

_Number = Annotated[
    float, Field(strict=True, allow_inf_nan=False, ge=-3.4028234e38, le=3.4028234e38)
]
_vectors = TypeAdapter(list[list[_Number]])


class EmbeddingProvider(Protocol):
    """Embed raw document texts in order; cache_key identifies the vector space."""

    model: str
    dimensions: int

    @property
    def cache_key(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...


class EmbeddingUnavailableError(Exception):
    """The local embedding service cannot be reached."""


class EmbeddingTimeoutError(Exception):
    """Embedding generation exceeded the HTTP timeout."""


class EmbeddingResponseError(Exception):
    """Embedding generation failed or returned unusable vectors."""


def validate_embeddings(value: object, count: int, dimensions: int) -> list[list[float]]:
    """Reject wrong counts, dimensions, non-finite values, and zero vectors."""
    try:
        vectors = _vectors.validate_python(value)
    except ValidationError:
        raise EmbeddingResponseError("Embedding service returned invalid numeric vectors.") from None
    if len(vectors) != count or any(len(vector) != dimensions for vector in vectors):
        raise EmbeddingResponseError(
            "Embedding count or dimensions do not match. Check EMBEDDING_MODEL and EMBEDDING_DIMENSIONS."
        )
    if any(not any(abs(number) >= 1.1754944e-38 for number in vector) for vector in vectors):
        raise EmbeddingResponseError("Embedding service returned a zero or unusably small vector.")
    return vectors
