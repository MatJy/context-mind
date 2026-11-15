"""Deterministic line windows over source files accepted by ingestion."""

from collections.abc import Iterable, Iterator

from app.schemas.chunk import ChunkingOptions, CodeChunk
from app.schemas.repository import SourceFile

MAX_CHUNKS = 20000
MAX_CHUNK_CONTENT_BYTES = 20 * 1024 * 1024


class ChunkingLimitError(Exception):
    """The in-memory chunk response would exceed its count or text limit."""


def iter_file_chunks(source: SourceFile, options: ChunkingOptions) -> Iterator[CodeChunk]:
    """Preserve line endings and stop once a window reaches the end of the file."""
    lines = source.content.splitlines(keepends=True)
    start = 0
    while start < len(lines):
        end = min(start + options.max_lines, len(lines))
        yield CodeChunk(
            file_path=source.file_path,
            start_line=start + 1,
            end_line=end,
            content="".join(lines[start:end]),
        )
        if end == len(lines):
            break
        start = end - options.overlap_lines


def chunk_files(files: Iterable[SourceFile], options: ChunkingOptions) -> list[CodeChunk]:
    """Keep file order, never cross file boundaries, and bound overlap expansion."""
    chunks: list[CodeChunk] = []
    total_bytes = 0
    for source in files:
        for chunk in iter_file_chunks(source, options):
            total_bytes += len(chunk.content.encode("utf-8"))
            if len(chunks) >= MAX_CHUNKS or total_bytes > MAX_CHUNK_CONTENT_BYTES:
                raise ChunkingLimitError(
                    "Chunk output exceeds 20,000 chunks or 20 MiB of text. "
                    "Increase max_lines, reduce overlap_lines, or scan a smaller repository."
                )
            chunks.append(chunk)
    return chunks
