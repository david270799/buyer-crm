"""File storage for images (never inside Firestore documents)."""

import threading
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urlparse


class BlobStorage(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> str:
        """Store `data` at `path` and return a URL the Mini App can load."""
        ...

    def read_url(self, url: str) -> bytes | None:
        """Contents of a file stored by `put`, or None if the URL is not ours or it is gone."""
        ...

    def delete_url(self, url: str) -> bool:
        """Remove the file behind a URL returned by `put`. False if the URL is not ours
        or the file is already gone; never raises for a missing file."""
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

    def _blob(self, url: str):
        parsed = urlparse(url)
        prefix = f"/v0/b/{self._bucket.name}/o/"
        if parsed.netloc != "firebasestorage.googleapis.com" or not parsed.path.startswith(prefix):
            return None
        return self._bucket.blob(unquote(parsed.path[len(prefix) :]))

    def read_url(self, url: str) -> bytes | None:
        blob = self._blob(url)
        if blob is None:
            return None
        try:
            return blob.download_as_bytes()
        except Exception:  # noqa: BLE001 - gone or no access
            return None

    def delete_url(self, url: str) -> bool:
        blob = self._blob(url)
        if blob is None:
            return False
        try:
            blob.delete()
        except Exception:  # noqa: BLE001 - already gone or no access: nothing to undo
            return False
        return True


class LocalBlobStorage:
    """Files in a local directory (the server's disk), served by the API under `base_url`."""

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
        partial = target.with_name(f".{target.name}.part")
        partial.write_bytes(data)
        partial.replace(target)  # never a half-written photo
        return f"{self._base_url}/{path}"

    def _file(self, url: str) -> Path | None:
        prefix = f"{self._base_url}/"
        if not url.startswith(prefix):
            return None
        target = (self._root / url[len(prefix) :]).resolve()
        if self._root.resolve() not in target.parents or not target.is_file():
            return None
        return target

    def read_url(self, url: str) -> bytes | None:
        target = self._file(url)
        return target.read_bytes() if target is not None else None

    def delete_url(self, url: str) -> bool:
        target = self._file(url)
        if target is None:
            return False
        target.unlink(missing_ok=True)
        return True


class MemoryBlobStorage:
    """For tests."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def put(self, path: str, data: bytes, content_type: str) -> str:
        with self._lock:
            self.files[path] = (data, content_type)
        return f"memory://{path}"

    def read_url(self, url: str) -> bytes | None:
        if not url.startswith("memory://"):
            return None
        with self._lock:
            entry = self.files.get(url[len("memory://") :])
        return entry[0] if entry else None

    def delete_url(self, url: str) -> bool:
        if not url.startswith("memory://"):
            return False
        with self._lock:
            return self.files.pop(url[len("memory://") :], None) is not None
