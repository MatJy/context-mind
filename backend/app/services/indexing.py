"""Reuse unchanged vectors, embed new content in batches, and save one snapshot."""

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeChunk, Repository
from app.schemas.chunk import CodeChunk as SourceChunk
from app.services.embeddings import EmbeddingProvider, validate_embeddings
from app.services.persistence import persist_repository


@dataclass
class IndexResult:
    repository: Repository
    embedded_chunk_count: int
    reused_chunk_count: int


def index_repository(
    session: Session, repository_path: str, chunks: list[SourceChunk],
    provider: EmbeddingProvider, batch_size: int,
) -> IndexResult:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    key = provider.cache_key
    # End the read transaction before waiting for model inference. The later
    # write transaction still replaces the complete snapshot atomically.
    with session.begin():
        rows = session.execute(
            select(CodeChunk.content_hash, CodeChunk.content, CodeChunk.embedding)
            .join(Repository, Repository.id == CodeChunk.repository_id)
            .where(Repository.path == repository_path, CodeChunk.embedding_key == key)
        )
        cached = {
            (row.content_hash, row.content): validate_embeddings(
                [list(row.embedding)], 1, provider.dimensions,
            )[0]
            for row in rows if row.embedding is not None
        }
    identities = [(sha256(chunk.content.encode("utf-8")).hexdigest(), chunk.content) for chunk in chunks]
    # Identical content at different source locations needs only one model call.
    missing = list(dict.fromkeys(identity for identity in identities if identity not in cached))
    vectors = dict(cached)
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        generated = validate_embeddings(
            provider.embed([content for _, content in batch]), len(batch), provider.dimensions,
        )
        vectors.update(zip(batch, generated, strict=True))
    repository = persist_repository(
        session, repository_path, chunks,
        embeddings=[vectors[identity] for identity in identities],
        embedding_model=provider.model, embedding_key=key,
    )
    reused = sum(identity in cached for identity in identities)
    return IndexResult(repository, len(chunks) - reused, reused)
