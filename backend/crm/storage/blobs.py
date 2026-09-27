"""File storage for images (never inside Firestore documents)."""

import threading
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote


class BlobStorage(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> str:
        """Store `data` at `path` and return a URL the Mini App can load."""
        ...


class FirebaseBlobStorage:
    """Firebase Storage with download-token URLs.

    Token URLs work with deny-all Storage rules and are unguessable, so
    images are readable only by whoever received the URL from our API.
    """

    def __init__(self, bucket):
        self._bucket = bucket

    def put(self, path: str, data: bytes, content_type: str) -> str:
        token = str(uuid.uuid4())
        blob = self._bucket.blob(path)
        blob.metadata = {"firebaseStorageDownloadTokens": token}
        blob.cache_control = "public, max-age=31536000, immutable"
        blob.upload_from_string(data, content_type=content_type)
        return (
            f"https://firebasestorage.googleapis.com/v0/b/{self._bucket.name}/o/"
            f"{quote(path, safe='')}?alt=media&token={token}"
        )


class LocalBlobStorage:
    """Files in a local directory, served by the API under `base_url` (demo mode)."""

    def __init__(self, root: Path, base_url: str = "/media"):
        self._root = root
        self._base_url = base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, path: str, data: bytes, content_type: str) -> str:
        target = (self._root / path).resolve()
        if self._root.resolve() not in target.parents:
            raise ValueError("Path escapes storage root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"{self._base_url}/{path}"


class MemoryBlobStorage:
    """For tests."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def put(self, path: str, data: bytes, content_type: str) -> str:
        with self._lock:
            self.files[path] = (data, content_type)
        return f"memory://{path}"
