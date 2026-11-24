"""Repository-grounded answers and references to the indexed snapshot."""

from pydantic import BaseModel

from app.schemas.retrieval import RetrievalRequest


class RAGRequest(RetrievalRequest):
    """Use the same question and top-k validation as semantic search."""


class SourceReference(BaseModel):
    source_id: int
    file_path: str
    start_line: int
    end_line: int


class RAGResponse(BaseModel):
    repository_id: int
    answer: str
    sources: list[SourceReference]
