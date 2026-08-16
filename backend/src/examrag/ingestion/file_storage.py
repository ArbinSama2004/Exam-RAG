"""Store uploaded files on disk and hash their contents.

Uploads are kept as files rather than in the database: they are re-read when a
document is re-ingested with a new chunker or embedding model, and the local
deployment already bind-mounts a directory for them.

The stored name is derived from the document ID, so two uploads that share a
filename cannot overwrite each other.
"""

import hashlib
import logging
import uuid
from pathlib import Path

from examrag.config import get_settings

logger = logging.getLogger(__name__)


def content_hash(data: bytes) -> str:
    """SHA-256 of the given bytes, used to recognise an unchanged re-upload."""
    return hashlib.sha256(data).hexdigest()


def upload_directory() -> Path:
    """The configured upload directory, created if it does not exist."""
    directory = get_settings().upload_dir
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_upload(document_id: uuid.UUID, filename: str, data: bytes) -> str:
    """Write an upload to disk.

    Returns:
        The path relative to the upload directory, as stored on the document.
    """
    stored_name = f"{document_id}{Path(filename).suffix.lower()}"
    (upload_directory() / stored_name).write_bytes(data)
    logger.info("Stored upload %s (%d bytes) as %s", filename, len(data), stored_name)
    return stored_name


def read_upload(stored_path: str) -> bytes:
    """Read a stored upload back.

    Raises:
        FileNotFoundError: the file is missing, e.g. the volume was cleared.
    """
    return (upload_directory() / stored_path).read_bytes()


def delete_upload(stored_path: str) -> None:
    """Remove a stored upload, ignoring one that is already gone."""
    (upload_directory() / stored_path).unlink(missing_ok=True)
