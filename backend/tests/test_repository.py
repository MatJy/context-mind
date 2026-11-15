"""Repository scanning against real temporary Git working trees."""

import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest

from app.main import create_app
from app.services import repository as service


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repository with spaces"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    return root


def write(root: Path, name: str, content: str | bytes = "sample\n") -> Path:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return target


def request_scan(body: object) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            return await client.post("/api/repositories/scan", json=body)
    return asyncio.run(send())


def test_source_content_metadata_and_deterministic_order(repo: Path) -> None:
    for extension in ("py", "js", "ts", "tsx", "jsx", "json", "md"):
        write(repo, f"src/example.{extension}", "first\r\nsecond\n")
    write(repo, "space name.PY", "print('héllo')")
    write(repo, "empty.md", "")
    write(repo, "bom.md", b"\xef\xbb\xbfhello\n")
    result = service.scan_repository(str(repo))
    paths = [file.file_path for file in result.files]
    assert paths == sorted(paths)
    assert len(paths) == 10
    sources = {file.file_path: file for file in result.files}
    assert sources["src/example.py"].content == "first\r\nsecond\n"
    assert sources["src/example.py"].line_count == 2
    assert sources["space name.PY"].size_bytes == len("print('héllo')".encode("utf-8"))
    assert sources["empty.md"].line_count == 0
    assert sources["bom.md"].content == "hello\n"
    assert result.repository_path == str(repo.resolve())


def test_ignores_untracked_files_but_reads_current_tracked_content(repo: Path) -> None:
    write(repo, ".gitignore", "ignored.py\n.cache/\n")
    write(repo, "src/.gitignore", "local.json\n")
    write(repo, "ignored.py")
    write(repo, ".cache/output.py")
    write(repo, "src/local.json")
    write(repo, "tracked.py", "old")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.py"], check=True)
    write(repo, "tracked.py", "current working tree")
    write(repo, "new.py", "untracked source")
    result = service.scan_repository(str(repo))
    assert {file.file_path: file.content for file in result.files} == {
        "new.py": "untracked source", "tracked.py": "current working tree",
    }


@pytest.mark.parametrize("name", [
    ".env", ".env.local", ".env.example", ".env.config.py", "config/.ENV.prod.json",
    "keys/server.pem", "keys/server.key", "keys/server.KEY", "keys/cert.p12",
    "credentials.json", "config/credentials.dev.json", "config/client_credentials.json",
    "secrets.json", "secret.json", "service-account-prod.json", "service_account.json",
    "serviceaccount.json", "id_rsa", "id_ed25519.json", ".aws/config.json",
    ".ssh/config.json", "secrets/config.py", "credentials/config.json",
    "node_modules/pkg/index.js", "nested/dist/main.js", "build/output.py",
    "coverage/data.json", ".venv/lib/code.py", "venv/code.py", "__pycache__/code.py",
    ".pytest_cache/data.json", ".next/routes.json", ".env.local/config.py",
])
def test_hard_exclusions_apply_even_when_tracked(repo: Path, name: str) -> None:
    write(repo, name, "DO_NOT_INGEST")
    subprocess.run(["git", "-C", str(repo), "add", "--force", "--", name], check=True)
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert len(result.skipped_files) == 1
    assert result.skipped_files[0].reason == "excluded"
    assert "DO_NOT_INGEST" not in result.model_dump_json()


@pytest.mark.parametrize("content", [b"\x00binary", b"\xff\xfe", b"hello\x01world"])
def test_binary_and_non_utf8_files_are_excluded(repo: Path, content: bytes) -> None:
    write(repo, "looks_like_source.py", content)
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert result.skipped_files[0].reason == "binary_or_non_utf8"


def test_private_key_marker_inside_source_is_excluded(repo: Path) -> None:
    write(repo, "ordinary.md", "-----BEGIN OPENSSH PRIVATE KEY-----\nplaceholder")
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert result.skipped_files[0].reason == "private_key"


def test_unsupported_and_oversized_files(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_FILE_BYTES", 8)
    write(repo, "image.png")
    write(repo, "big.py", "x" * 9)
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert {file.reason for file in result.skipped_files} == {"unsupported_extension", "too_large"}


def test_deleted_tracked_file_is_skipped(repo: Path) -> None:
    target = write(repo, "deleted.py")
    subprocess.run(["git", "-C", str(repo), "add", "deleted.py"], check=True)
    target.unlink()
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert result.skipped_files[0].reason == "unreadable"


def test_symlink_is_not_read(repo: Path, tmp_path: Path) -> None:
    outside = write(tmp_path, "outside.py", "DO_NOT_INGEST")
    link = repo / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privileges")
    result = service.scan_repository(str(repo))
    assert result.files == []
    assert result.skipped_files[0].reason == "unsafe_path"


def test_linked_parent_is_not_read(repo: Path, tmp_path: Path) -> None:
    target = write(repo, "src/main.py", "safe")
    subprocess.run(["git", "-C", str(repo), "add", "src/main.py"], check=True)
    target.unlink()
    target.parent.rmdir()
    outside = tmp_path / "outside"
    write(outside, "main.py", "DO_NOT_INGEST")
    try:
        (repo / "src").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privileges")
    assert service.scan_repository(str(repo)).files == []


def test_api_returns_source_files(repo: Path) -> None:
    write(repo, "main.py", "print('hello')\n")
    response = request_scan({"path": str(repo)})
    assert response.status_code == 200
    assert response.json()["files"] == [{
        "file_path": "main.py", "content": "print('hello')\n", "size_bytes": 15,
        "line_count": 1,
    }]


@pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": " "}, {"path": 123},
                                      {"path": None}, {"path": "x" * 4097}])
def test_api_validation(body: object) -> None:
    assert request_scan(body).status_code == 422


def test_invalid_paths_return_400(tmp_path: Path) -> None:
    for path in [str(tmp_path / "missing"), str(tmp_path), "relative/path", "bad\0path"]:
        assert request_scan({"path": path}).status_code == 400
    file_path = write(tmp_path, "file.py")
    assert request_scan({"path": str(file_path)}).status_code == 400


def test_empty_repository(repo: Path) -> None:
    response = request_scan({"path": str(repo)})
    assert response.status_code == 200
    assert response.json()["files"] == []


@pytest.mark.parametrize("limit", ["MAX_TOTAL_BYTES", "MAX_CANDIDATES"])
def test_scan_limits_return_413(repo: Path, monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    write(repo, "one.py", "hello")
    monkeypatch.setattr(service, limit, 0)
    assert request_scan({"path": str(repo)}).status_code == 413


@pytest.mark.parametrize(("error", "status"), [
    (FileNotFoundError(), 503),
    (subprocess.TimeoutExpired("git", 30), 504),
    (subprocess.CalledProcessError(128, "git", stderr=b"private details"), 400),
])
def test_git_failures(repo: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise error
    monkeypatch.setattr(service.subprocess, "run", fail)
    response = request_scan({"path": str(repo)})
    assert response.status_code == status
    assert "private details" not in response.text
