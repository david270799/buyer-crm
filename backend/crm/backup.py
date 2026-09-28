"""Backups of the SQLite database.

A backup is a consistent copy of the live database, gzip-compressed, named
`crm-YYYYMMDD-HHMMSS.sqlite3.gz` (Seoul time). The newest `keep` are kept.
The bot makes one every night and sends it to the admins in Telegram, so a
copy always exists outside the server. Photos are not included (they are
large and can be re-sent); everything about money and orders is.

    python -m crm.tools.backup              # make a backup now
    python -m crm.tools.backup --restore F  # restore (the server must be stopped)
"""

import gzip
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from crm.domain.timeutil import to_local
from crm.storage import StorageError
from crm.storage.sqlite import SqliteDatabase, backup_to

PATTERN = "crm-*.sqlite3.gz"


def make_backup(db_path: Path, backup_dir: Path, now: datetime, keep: int = 14) -> Path:
    if not db_path.is_file():
        raise StorageError(f"Файл базы не найден: {db_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = to_local(now).strftime("%Y%m%d-%H%M%S")
    plain = backup_dir / f".crm-{stamp}.sqlite3"
    backup_to(db_path, plain)
    archive = backup_dir / f"crm-{stamp}.sqlite3.gz"
    partial = archive.with_name(archive.name + ".part")
    with plain.open("rb") as src, gzip.open(partial, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    os.replace(partial, archive)
    plain.unlink()
    for old in sorted(backup_dir.glob(PATTERN))[:-keep]:
        old.unlink()
    return archive


def list_backups(backup_dir: Path) -> list[Path]:
    return sorted(backup_dir.glob(PATTERN)) if backup_dir.is_dir() else []


def restore_backup(archive: Path, db_path: Path, now: datetime) -> Path | None:
    """Replace the database with `archive`. Returns where the old file was kept.

    Refuses while the CRM is running (it holds the database lock) and checks
    the backup before touching the current database.
    """
    if not archive.is_file():
        raise StorageError(f"Файл копии не найден: {archive}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    guard = SqliteDatabase(db_path)  # takes the lock: fails if the server runs
    guard.close()
    candidate = db_path.with_name(db_path.name + ".restoring")
    opener = gzip.open if archive.suffix == ".gz" else open
    with opener(archive, "rb") as src, candidate.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    try:
        conn = sqlite3.connect(candidate)
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        has_docs = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'documents'"
        ).fetchone()[0]
        conn.close()
    except sqlite3.DatabaseError:
        ok, has_docs = False, 0
    if not ok or not has_docs:
        candidate.unlink()
        raise StorageError(f"Копия повреждена или это не база CRM: {archive}")

    kept = None
    if db_path.exists():
        stamp = to_local(now).strftime("%Y%m%d-%H%M%S")
        kept = db_path.with_name(f"{db_path.name}.before-restore-{stamp}")
        os.replace(db_path, kept)
    for suffix in ("-wal", "-shm"):
        leftover = db_path.with_name(db_path.name + suffix)
        if leftover.exists():
            leftover.unlink()
    os.replace(candidate, db_path)
    return kept
