"""Semantic search requests and source matches, without LLM generation."""

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from app.schemas.chunk import CodeChunk


class RetrievalRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    top_k: int | None = Field(default=None, ge=1, le=20, strict=True)


class RetrievalMatch(CodeChunk):
    similarity: float


class RetrievalResponse(BaseModel):
    repository_id: int
    question: str
    top_k: int
    matches: list[RetrievalMatch]
