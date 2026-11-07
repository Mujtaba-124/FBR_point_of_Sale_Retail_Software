"""Private storage for original Excel uploads.

- Files live under ``UPLOAD_STORAGE_DIR`` (a Docker volume), never in a
  temporary directory and never served directly: downloads go through an
  authorized API route that re-checks the SHA-256 checksum.
- Keys are generated (``YYYY/MM/<random>.xlsx``): collision-safe, not
  guessable, and never derived from the user's file name. Only keys of that
  exact shape are accepted, so no path traversal is possible.
- Writes are atomic: a temporary file in the same directory is fsynced and
  renamed into place. A failed database transaction deletes the new file
  (compensation), so aborted saves leave nothing behind.
"""

import hashlib
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^\d{4}/\d{2}/[0-9a-f]{32}\.xlsx$")


@dataclass(frozen=True)
class StoredFile:
    key: str
    checksum_sha256: str
    size: int


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root() -> Path:
    return Path(get_settings().upload_storage_dir)


def _path_for(key: str) -> Path:
    if not KEY_RE.match(key):
        raise AppError(500, "storage_error", "The stored file reference is invalid.")
    return _root() / key


def save(data: bytes) -> StoredFile:
    """Store bytes under a new random key (atomic, fsynced)."""
    now = datetime.now(UTC)
    key = f"{now:%Y}/{now:%m}/{secrets.token_hex(16)}.xlsx"
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        logger.exception("upload storage write failed")
        raise AppError(
            503, "storage_unavailable", "The file could not be stored. Please try again."
        ) from None
    return StoredFile(key=key, checksum_sha256=checksum(data), size=len(data))


def discard(key: str) -> None:
    """Compensation only: remove a file whose database transaction failed."""
    try:
        _path_for(key).unlink(missing_ok=True)
    except (OSError, AppError):
        logger.exception("could not discard an unused upload file")


def read(key: str, expected_checksum: str) -> bytes:
    """Read a stored original and verify its checksum."""
    try:
        data = _path_for(key).read_bytes()
    except FileNotFoundError:
        logger.error("stored upload missing", extra={"key": key})
        raise AppError(
            410, "original_file_missing", "The original file is no longer available."
        ) from None
    if checksum(data) != expected_checksum:
        logger.error("stored upload checksum mismatch", extra={"key": key})
        raise AppError(
            500,
            "original_file_corrupt",
            "The original file failed its integrity check. Contact your administrator.",
        )
    return data
