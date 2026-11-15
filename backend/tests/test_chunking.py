"""Chunk coverage, exact references, and repository endpoint integration."""

import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api import repositories as routes
from app.main import create_app
from app.schemas.chunk import ChunkingOptions
from app.schemas.repository import SourceFile
from app.services import chunking
from app.services.repository import (
    GitTimeoutError, GitUnavailableError, RepositoryLimitError, RepositoryScanError,
)


def source(content: str, path: str = "src/example.py") -> SourceFile:
    return SourceFile(
        file_path=path, content=content, size_bytes=len(content.encode("utf-8")),
        line_count=len(content.splitlines()),
    )


def request_chunks(body: object) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            return await client.post("/api/repositories/chunks", json=body)
    return asyncio.run(send())


def test_default_windows_and_overlap() -> None:
    text = "".join(f"line {number}\n" for number in range(1, 161))
    chunks = chunking.chunk_files([source(text)], ChunkingOptions())
    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [
        (1, 80), (71, 150), (141, 160),
    ]
    assert chunks[0].content.splitlines(keepends=True)[-10:] == (
        chunks[1].content.splitlines(keepends=True)[:10]
    )


@pytest.mark.parametrize("line_count", [0, 1, 4, 5, 6, 8, 9, 10, 11, 20])
@pytest.mark.parametrize("overlap", [0, 1, 4])
def test_every_line_is_covered_with_exact_content(line_count: int, overlap: int) -> None:
    lines = [f"line {index}\n" for index in range(line_count)]
    chunks = chunking.chunk_files(
        [source("".join(lines))], ChunkingOptions(max_lines=5, overlap_lines=overlap)
    )
    covered: set[int] = set()
    for index, chunk in enumerate(chunks):
        assert chunk.file_path == "src/example.py"
        assert chunk.content == "".join(lines[chunk.start_line - 1:chunk.end_line])
        assert 1 <= chunk.end_line - chunk.start_line + 1 <= 5
        covered.update(range(chunk.start_line, chunk.end_line + 1))
        if index:
            assert chunk.start_line == chunks[index - 1].end_line - overlap + 1
    assert covered == set(range(1, line_count + 1))
    if chunks:
        assert chunks[-1].end_line == line_count
        # Don't emit a redundant final window consisting only of overlap.
        assert len(chunks) == 1 or chunks[-2].end_line < line_count


@pytest.mark.parametrize("text", [
    "", "\n", "\n\n", "  \n\t\n", "one", "one\n", "one\r\ntwo\r\nthree",
    "one\rtwo\rthree\r", "héllo\n世界\nlast", "one\u2028two\nthree",
])
def test_preserves_whitespace_unicode_and_line_endings(text: str) -> None:
    chunks = chunking.chunk_files(
        [source(text)], ChunkingOptions(max_lines=2, overlap_lines=0)
    )
    assert "".join(chunk.content for chunk in chunks) == text
    if text:
        assert chunks[-1].end_line == len(text.splitlines())
    else:
        assert chunks == []


def test_files_never_share_chunks_and_line_numbers_restart() -> None:
    files = [source("first\nsecond\n", "a.py"), source("", "empty.md"),
             source("third", "b.ts")]
    options = ChunkingOptions(max_lines=2, overlap_lines=1)
    result = chunking.chunk_files(files, options)
    assert [chunk.model_dump() for chunk in result] == [
        {"file_path": "a.py", "start_line": 1, "end_line": 2, "content": "first\nsecond\n"},
        {"file_path": "b.ts", "start_line": 1, "end_line": 1, "content": "third"},
    ]
    assert result == chunking.chunk_files(files, options)


def test_long_line_is_preserved() -> None:
    text = "x" * 10000
    chunks = chunking.chunk_files([source(text)], ChunkingOptions())
    assert len(chunks) == 1
    assert chunks[0].content == text


@pytest.mark.parametrize("options", [
    {"max_lines": 0}, {"max_lines": -1}, {"max_lines": 501},
    {"max_lines": True}, {"max_lines": 1.5}, {"max_lines": "80"},
    {"overlap_lines": -1}, {"overlap_lines": 101}, {"overlap_lines": False},
    {"overlap_lines": "10"}, {"max_lines": 10, "overlap_lines": 10},
    {"max_lines": 5, "overlap_lines": 6},
])
def test_invalid_options_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChunkingOptions.model_validate(options)


def test_chunk_count_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunking, "MAX_CHUNKS", 2)
    options = ChunkingOptions(max_lines=1, overlap_lines=0)
    assert len(chunking.chunk_files([source("a\nb\n")], options)) == 2
    with pytest.raises(chunking.ChunkingLimitError):
        chunking.chunk_files([source("a\nb\nc\n")], options)


def test_text_limit_counts_utf8_bytes_and_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunking, "MAX_CHUNK_CONTENT_BYTES", 6)
    options = ChunkingOptions(max_lines=2, overlap_lines=1)
    assert len(chunking.chunk_files([source("é\né\n")], options)) == 1
    # Three lines fit under nine source bytes, but overlap expands output to twelve.
    monkeypatch.setattr(chunking, "MAX_CHUNK_CONTENT_BYTES", 9)
    with pytest.raises(chunking.ChunkingLimitError):
        chunking.chunk_files([source("é\né\né\n")], options)


def test_api_scans_then_chunks_and_keeps_exclusions(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "example.py").write_bytes(b"one\r\ntwo\r\nthree\r\nfour\r\n")
    (tmp_path / ".env").write_text("DUMMY_SECRET", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("DUMMY_SECRET", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"\x00DUMMY_BINARY")
    (tmp_path / "empty.md").write_bytes(b"")
    body = {"path": str(tmp_path), "chunking": {"max_lines": 3, "overlap_lines": 1}}
    response = request_chunks(body)
    assert response.status_code == 200
    result = response.json()
    assert result["repository_path"] == str(tmp_path.resolve())
    assert result["chunking"] == {"max_lines": 3, "overlap_lines": 1}
    assert result["chunks"] == [
        {"file_path": "example.py", "start_line": 1, "end_line": 3,
         "content": "one\r\ntwo\r\nthree\r\n"},
        {"file_path": "example.py", "start_line": 3, "end_line": 4,
         "content": "three\r\nfour\r\n"},
    ]
    assert {file["file_path"] for file in result["skipped_files"]} == {
        ".env", "credentials.json", "binary.py",
    }
    assert "DUMMY_SECRET" not in response.text
    assert "DUMMY_BINARY" not in response.text
    assert request_chunks(body).json() == result


def test_empty_repository_uses_default_options(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    response = request_chunks({"path": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["chunks"] == []
    assert response.json()["chunking"] == {"max_lines": 80, "overlap_lines": 10}


@pytest.mark.parametrize("body", [
    {}, {"path": ""}, {"path": 1}, {"path": "somewhere", "chunking": None},
    {"path": "somewhere", "chunking": {"max_lines": 10, "overlap_lines": 10}},
    {"path": "somewhere", "chunking": {"max_lines": "80"}},
])
def test_invalid_requests_do_not_scan(body: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(path: str) -> None:
        pytest.fail("Invalid chunk requests must not scan the filesystem")
    monkeypatch.setattr(routes, "scan_repository", unexpected)
    assert request_chunks(body).status_code == 422


@pytest.mark.parametrize(("error", "status"), [
    (RepositoryScanError("Invalid repository"), 400),
    (RepositoryLimitError("Too much source content"), 413),
    (GitUnavailableError("Git missing"), 503),
    (GitTimeoutError("Git timed out"), 504),
])
def test_scanner_error_statuses_are_preserved(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status: int,
) -> None:
    def fail(path: str) -> None:
        raise error
    monkeypatch.setattr(routes, "scan_repository", fail)
    response = request_chunks({"path": "somewhere"})
    assert response.status_code == status
    assert response.json() == {"detail": str(error)}


def test_chunk_limit_returns_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "example.py").write_text("one\ntwo\n", encoding="utf-8")
    monkeypatch.setattr(chunking, "MAX_CHUNKS", 0)
    response = request_chunks({"path": str(tmp_path)})
    assert response.status_code == 413
