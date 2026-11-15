"""Repository scan input and source-file metadata for later chunking."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RepositoryScanRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(min_length=1, max_length=4096)


class SourceFile(BaseModel):
    """A UTF-8 source file with a repository-relative, slash-separated path."""

    file_path: str
    content: str
    size_bytes: int
    line_count: int


class SkippedFile(BaseModel):
    file_path: str
    reason: Literal[
        "excluded", "unsupported_extension", "unsafe_path", "unreadable",
        "binary_or_non_utf8", "too_large", "private_key",
    ]


class RepositoryScanResponse(BaseModel):
    repository_path: str
    files: list[SourceFile]
    skipped_files: list[SkippedFile]
