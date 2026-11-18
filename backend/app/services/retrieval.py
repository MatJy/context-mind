"""Repository-scoped exact cosine search using PostgreSQL's pgvector operator."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeChunk, Repository
from app.schemas.retrieval import RetrievalMatch
from app.services.embeddings import EmbeddingProvider, validate_embeddings


class RepositoryNotFoundError(Exception):
    """No indexed repository has the requested ID."""


class RetrievalIndexError(Exception):
    """The snapshot needs embedding with the active provider configuration."""


def retrieve_chunks(
    session: Session, repository_id: int, question: str,
    provider: EmbeddingProvider, top_k: int,
) -> list[RetrievalMatch]:
    """Return best matches; never compare vectors from different configurations."""
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    # Hold a shared row lock through retrieval so re-indexing cannot replace the
    # snapshot between checking its vector space and searching it.
    repository = session.scalar(
        select(Repository.id).where(Repository.id == repository_id).with_for_update(read=True)
    )
    if repository is None:
        raise RepositoryNotFoundError("Indexed repository not found. Index it first.")
    metadata = session.execute(
        select(CodeChunk.embedding_key, CodeChunk.embedding_model)
        .where(CodeChunk.repository_id == repository_id).distinct()
    ).all()
    if not metadata:
        return []
    if any(key != provider.cache_key or model != provider.model for key, model in metadata):
        raise RetrievalIndexError(
            "Repository embeddings do not match the current configuration. Re-index this repository."
        )

    vector = validate_embeddings([provider.embed_query(question)], 1, provider.dimensions)[0]
    distance = CodeChunk.embedding.cosine_distance(vector).label("distance")
    rows = session.execute(
        select(CodeChunk, distance)
        .where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.embedding_key == provider.cache_key,
            CodeChunk.embedding_model == provider.model,
            CodeChunk.embedding.is_not(None),
        )
        .order_by(distance, CodeChunk.file_path, CodeChunk.start_line, CodeChunk.id)
        .limit(top_k)
    ).all()
    return [
        RetrievalMatch(
            file_path=chunk.file_path, content=chunk.content,
            start_line=chunk.start_line, end_line=chunk.end_line,
            similarity=max(-1.0, min(1.0, 1.0 - float(cosine_distance))),
        )
        for chunk, cosine_distance in rows
    ]
