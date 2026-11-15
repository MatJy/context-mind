"""Line-based chunking options and source references."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.repository import RepositoryScanRequest, SkippedFile


class ChunkingOptions(BaseModel):
    """Bounded line windows; overlap must leave room for forward progress."""

    max_lines: int = Field(default=80, ge=1, le=500, strict=True)
    overlap_lines: int = Field(default=10, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.overlap_lines >= self.max_lines:
            raise ValueError("overlap_lines must be smaller than max_lines")
        return self


class CodeChunk(BaseModel):
    """Exact source text with one-based, inclusive line references."""

    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str


class RepositoryChunkRequest(RepositoryScanRequest):
    chunking: ChunkingOptions = Field(default_factory=ChunkingOptions)


class RepositoryChunkResponse(BaseModel):
    repository_path: str
    chunking: ChunkingOptions
    chunks: list[CodeChunk]
    skipped_files: list[SkippedFile]
