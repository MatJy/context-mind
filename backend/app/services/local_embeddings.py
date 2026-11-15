"""Local embedding inference served by Ollama; no cloud API is required."""

from hashlib import sha256
import json

import httpx

from app.services.embeddings import (
    EmbeddingResponseError, EmbeddingTimeoutError, EmbeddingUnavailableError,
    validate_embeddings,
)


class LocalEmbeddingProvider:
    """Synchronous HTTP fits the existing indexing route's worker-thread execution."""

    def __init__(self, client: httpx.Client, model: str, dimensions: int) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self.document_prefix = "search_document: " if model.split(":")[0] == "nomic-embed-text" else ""

    @property
    def cache_key(self) -> str:
        identity = {
            "provider": "local-ollama-v1", "base_url": str(self.client.base_url),
            "model": self.model, "dimensions": self.dimensions,
            "document_prefix": self.document_prefix,
        }
        return sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.post(
                "api/embed", json={
                    "model": self.model,
                    "input": [self.document_prefix + text for text in texts],
                    "truncate": False,
                },
            )
        except httpx.TimeoutException:
            raise EmbeddingTimeoutError(
                "Local embeddings timed out. Retry or increase EMBEDDING_TIMEOUT_SECONDS."
            ) from None
        except httpx.ConnectError:
            raise EmbeddingUnavailableError(
                "Cannot reach local embeddings. Start Ollama and check EMBEDDING_BASE_URL."
            ) from None
        except httpx.RequestError:
            raise EmbeddingResponseError("Communication with the embedding service failed.") from None
        if response.status_code == 404:
            raise EmbeddingResponseError(
                "Embedding model or endpoint not found. Pull EMBEDDING_MODEL with Ollama "
                "and check EMBEDDING_BASE_URL."
            )
        if not response.is_success:
            raise EmbeddingResponseError(
                "Local embedding generation failed. Check the model and Ollama logs. "
                "If a chunk exceeds the model context, reduce chunking.max_lines; input is not truncated."
            )
        try:
            result = response.json()
        except ValueError:
            raise EmbeddingResponseError("Embedding service returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise EmbeddingResponseError("Embedding service returned an invalid response.")
        return validate_embeddings(result.get("embeddings"), len(texts), self.dimensions)
