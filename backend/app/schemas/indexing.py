"""Stored repository summary returned after indexing."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.repository import SkippedFile


class RepositoryIndexResponse(BaseModel):
    id: int
    name: str
    path: str
    indexed_at: datetime
    chunk_count: int
    embedding_model: str
    embedded_chunk_count: int
    reused_chunk_count: int
    skipped_files: list[SkippedFile]
