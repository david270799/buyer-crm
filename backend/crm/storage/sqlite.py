"""Database in one SQLite file on the server (the default storage).

The working set lives in memory — the InMemoryDatabase engine, which enforces
the same transaction rules as Firestore and passes the same contract tests —
and every commit is first written to SQLite in a single SQL transaction:

* a commit that does not reach the disk is not applied at all;
* after a restart everything that was committed is loaded back;
* WAL journal with synchronous=FULL: a committed change survives a power cut;
* transactions run one at a time (single process), so they never conflict.

For this CRM (hundreds of orders, thousands of events) the whole database is
a few megabytes, so keeping it in memory is cheap and makes reads instant.

Exactly one process may write: the CRM server (API + bot). A lock file stops
a second one from starting against the same file. Tools such as `doctor`
open the file read-only.

Storage: table `documents(collection, id, data, updated_at)`, `data` is JSON
(datetimes as {"$dt": "<ISO 8601>"}). Views `orders_v` and `transactions_v`
give plain columns for SQL reports.
"""

import base64
import json
import os
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from crm.storage.base import Doc, StorageError, T, Transaction
from crm.storage.memory import InMemoryDatabase

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    collection TEXT NOT NULL,
    id         TEXT NOT NULL,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (collection, id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS orders_v AS
SELECT id                                              AS order_id,
       json_extract(data, '$.status')                  AS status,
       json_extract(data, '$.brand')                   AS brand,
       json_extract(data, '$.model')                   AS model,
       json_extract(data, '$.size')                    AS size,
       json_extract(data, '$.purchase_price')          AS purchase_price,
       json_extract(data, '$.client_price')            AS client_price,
       json_extract(data, '$.profit')                  AS profit,
       json_extract(data, '$.charged_amount_krw')      AS charged_krw,
       json_extract(data, '$.shipment_id')             AS shipment_id,
       json_extract(data, '$.created_at."$dt"')        AS created_at
FROM documents WHERE collection = 'orders';
CREATE VIEW IF NOT EXISTS transactions_v AS
SELECT id                                              AS entry_id,
       json_extract(data, '$.type')                    AS type,
       json_extract(data, '$.amount_krw')              AS amount_krw,
       json_extract(data, '$.balance_after')           AS balance_after,
       json_extract(data, '$.order_id')                AS order_id,
       json_extract(data, '$.shipment_id')             AS shipment_id,
       json_extract(data, '$.comment')                 AS comment,
       json_extract(data, '$.created_at."$dt"')        AS created_at
FROM documents WHERE collection = 'transactions';
"""


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, bytes):
        return {"$b64": base64.b64encode(value).decode()}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if len(value) == 1 and "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if len(value) == 1 and "$b64" in value:
            return base64.b64decode(value["$b64"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def dumps(data: Doc) -> str:
    return json.dumps(_encode(data), ensure_ascii=False, separators=(",", ":"))


def loads(text: str) -> Doc:
    return _decode(json.loads(text))


def _lock(path: Path) -> BinaryIO:
    """Exclusive lock next to the database, held while the process runs."""
    handle = open(path.with_name(path.name + ".lock"), "a+b")  # noqa: SIM115 - kept open
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # Windows
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise StorageError(
            f"База {path} уже открыта другим процессом CRM. Остановите его и запустите снова."
        ) from None
    return handle


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class SqliteDatabase(InMemoryDatabase):
    def __init__(self, path: str | Path, *, read_only: bool = False, max_attempts: int = 5):
        super().__init__(max_attempts=max_attempts)
        self.path = Path(path)
        self.read_only = read_only
        self._lock_handle: BinaryIO | None = None
        self._sql_lock = threading.Lock()
        self._tx_lock = threading.RLock()
        if read_only:
            if not self.path.is_file():
                raise StorageError(f"Файл базы не найден: {self.path}")
            self._conn = connect(self.path, read_only=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_handle = _lock(self.path)
            self._conn = connect(self.path)
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self._load()

    def run_transaction(self, fn: Callable[[Transaction], T]) -> T:
        # One process owns the database, so transactions simply run one at a
        # time: no optimistic conflicts, no retries. They are short (reads and
        # writes only), while plain reads outside transactions stay concurrent.
        with self._tx_lock:
            return super().run_transaction(fn)

    def _load(self) -> None:
        rows = self._conn.execute("SELECT collection, id, data FROM documents").fetchall()
        with self._lock:
            for collection, doc_id, data in rows:
                self._docs[collection][doc_id] = (self._next_version, loads(data))
                self._collection_versions[collection] += 1
                self._next_version += 1

    def _persist(self, staged: dict[tuple[str, str], Doc | None]) -> None:
        if self.read_only:
            raise StorageError("База открыта только для чтения.")
        if not staged:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = [(c, i, dumps(data), now) for (c, i), data in staged.items() if data is not None]
        deleted = [(c, i) for (c, i), data in staged.items() if data is None]
        with self._sql_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.executemany(
                    "INSERT INTO documents(collection, id, data, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(collection, id) DO UPDATE SET "
                    "data = excluded.data, updated_at = excluded.updated_at",
                    rows,
                )
                self._conn.executemany(
                    "DELETE FROM documents WHERE collection = ? AND id = ?", deleted
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error as exc:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise StorageError(f"Не удалось записать изменения в базу: {exc}") from exc

    def document_count(self) -> int:
        with self._sql_lock:
            return self._conn.execute("SELECT count(*) FROM documents").fetchone()[0]

    def close(self) -> None:
        with self._sql_lock:
            self._conn.close()
        if self._lock_handle is not None:
            self._lock_handle.close()
            self._lock_handle = None

    def __del__(self) -> None:  # pragma: no cover - best effort on interpreter exit
        handle = getattr(self, "_lock_handle", None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


def backup_to(source: Path, destination: Path) -> None:
    """Consistent copy of a live database (safe while the server is running)."""
    tmp = destination.with_name(destination.name + ".part")
    if tmp.exists():
        tmp.unlink()
    src = connect(source, read_only=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, destination)
