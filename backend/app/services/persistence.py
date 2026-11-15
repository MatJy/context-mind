"""Persist a complete scan as one atomic repository snapshot."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CodeChunk, Repository
from app.schemas.chunk import CodeChunk as SourceChunk


def persist_repository(
    session: Session, repository_path: str, chunks: list[SourceChunk],
    *, embeddings: list[list[float]] | None = None,
    embedding_model: str | None = None, embedding_key: str | None = None,
) -> Repository:
    """Replace old chunks only if the entire transaction commits successfully."""
    if embeddings is not None and (
        len(embeddings) != len(chunks) or not embedding_model or not embedding_key
    ):
        raise ValueError("Each chunk needs an embedding and model identity")
    if embeddings is None and (embedding_model is not None or embedding_key is not None):
        raise ValueError("Embedding metadata requires embeddings")
    with session.begin():
        repository = session.scalar(
            select(Repository).where(Repository.path == repository_path).with_for_update()
        )
        if repository is None:
            repository = Repository(path=repository_path, name=Path(repository_path).name)
            session.add(repository)
        repository.indexed_at = datetime.now(timezone.utc)
        session.flush()
        session.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository.id))
        session.add_all([
            CodeChunk(
                repository_id=repository.id, file_path=chunk.file_path,
                content=chunk.content, start_line=chunk.start_line, end_line=chunk.end_line,
                content_hash=sha256(chunk.content.encode("utf-8")).hexdigest(),
                embedding=embeddings[index] if embeddings is not None else None,
                embedding_model=embedding_model, embedding_key=embedding_key,
            )
            for index, chunk in enumerate(chunks)
        ])
    return repository
