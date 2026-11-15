"""Read source files from one local Git working tree without modifying it."""

import os
import re
import stat
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from app.schemas.repository import RepositoryScanResponse, SkippedFile, SourceFile

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md"}
EXCLUDED_DIRECTORIES = {
    ".git", "node_modules", "dist", "build", "coverage", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next",
    ".ssh", ".aws", ".azure", ".secrets", "secrets", "credentials",
}
SECRET_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*",
    "id_ed25519*", "id_ecdsa*", "credentials*", "*credentials.json",
    "secret.*", "secrets.*", "service-account*.json", "service_account*.json",
    "serviceaccount*.json", ".netrc", ".npmrc", ".pypirc",
)
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_CANDIDATES = 20000
GIT_TIMEOUT_SECONDS = 30
PRIVATE_KEY_MARKER = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


class RepositoryScanError(Exception):
    """Invalid repository or failure to enumerate its working tree."""


class GitUnavailableError(RepositoryScanError):
    """Git is not installed or cannot be executed."""


class GitTimeoutError(RepositoryScanError):
    """Git did not finish within the scan timeout."""


class RepositoryLimitError(RepositoryScanError):
    """The repository exceeds the initial in-memory scan limits."""


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True, check=True, timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitUnavailableError("Git is not installed or is not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitTimeoutError("Git repository scan timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise RepositoryScanError(
            "Git could not read this repository. Check its validity and permissions."
        ) from exc
    except OSError as exc:
        raise GitUnavailableError("Git could not be started. Check its installation.") from exc
    return result.stdout


def _excluded(path: PurePosixPath) -> bool:
    """Apply hard exclusions even to files explicitly tracked by Git."""
    parts = [part.lower() for part in path.parts]
    return any(part in EXCLUDED_DIRECTORIES for part in parts[:-1]) or any(
        fnmatchcase(part, pattern) for part in parts for pattern in SECRET_PATTERNS
    )


def _safe_regular_file(root: Path, relative: PurePosixPath) -> Path | None:
    """Reject traversal, links, Windows junctions, and non-regular files."""
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
        return None
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            return None
    if not candidate.resolve().is_relative_to(root) or not stat.S_ISREG(info.st_mode):
        return None
    return candidate


def scan_repository(path: str) -> RepositoryScanResponse:
    """Return current working-tree content; do not persist or send it to an LLM."""
    try:
        root = Path(path)
        if not root.is_absolute():
            raise RepositoryScanError("Provide an absolute local repository path.")
        root = root.resolve(strict=True)
        if not root.is_dir() or not (root / ".git").exists():
            raise RepositoryScanError("Provide the root directory of a local Git repository.")
    except (OSError, ValueError, RuntimeError) as exc:
        raise RepositoryScanError("Repository path does not exist or cannot be accessed.") from exc

    # Git handles nested .gitignore rules without an extra parsing dependency.
    # NUL delimiters preserve spaces and newlines in file names; a set removes duplicates.
    listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    names = sorted(set(name for name in listing.split(b"\0") if name))
    if len(names) > MAX_CANDIDATES:
        raise RepositoryLimitError("Repository exceeds the 20,000-file scan limit.")

    files: list[SourceFile] = []
    skipped: list[SkippedFile] = []
    total_bytes = 0
    for name in names:
        relative = PurePosixPath(os.fsdecode(name))
        file_path = relative.as_posix()
        if _excluded(relative):
            skipped.append(SkippedFile(file_path=file_path, reason="excluded"))
            continue
        if relative.suffix.lower() not in SUPPORTED_EXTENSIONS:
            skipped.append(SkippedFile(file_path=file_path, reason="unsupported_extension"))
            continue
        try:
            candidate = _safe_regular_file(root, relative)
            if candidate is None:
                skipped.append(SkippedFile(file_path=file_path, reason="unsafe_path"))
                continue
            # Bound the read even if the file grows after being enumerated.
            with candidate.open("rb") as source:
                data = source.read(MAX_FILE_BYTES + 1)
        except (OSError, ValueError):
            skipped.append(SkippedFile(file_path=file_path, reason="unreadable"))
            continue
        if len(data) > MAX_FILE_BYTES:
            skipped.append(SkippedFile(file_path=file_path, reason="too_large"))
            continue
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            skipped.append(SkippedFile(file_path=file_path, reason="binary_or_non_utf8"))
            continue
        if any(ord(char) < 32 and char not in "\t\n\r" for char in content):
            skipped.append(SkippedFile(file_path=file_path, reason="binary_or_non_utf8"))
            continue
        if PRIVATE_KEY_MARKER.search(content):
            skipped.append(SkippedFile(file_path=file_path, reason="private_key"))
            continue
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise RepositoryLimitError("Repository exceeds the 10 MiB source-content limit.")
        files.append(SourceFile(
            file_path=file_path, content=content, size_bytes=len(data),
            line_count=len(content.splitlines()),
        ))
    return RepositoryScanResponse(
        repository_path=str(root), files=files, skipped_files=skipped,
    )
