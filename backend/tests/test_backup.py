"""Backups: nightly job, pruning, restore with checks."""

import gzip
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from crm.backup import list_backups, make_backup, restore_backup
from crm.bot.backups import NightlyBackup, seconds_until
from crm.storage import StorageError
from crm.storage.sqlite import SqliteDatabase

NOW = datetime(2026, 9, 27, 19, 0, tzinfo=UTC)  # 04:00 in Seoul on the 28th


def _db(tmp_path, value=1):
    path = tmp_path / "data" / "crm.sqlite3"
    db = SqliteDatabase(path)
    db.run_transaction(lambda tx: tx.set("orders", "N1", {"v": value}))
    return db, path


def test_backup_is_compressed_consistent_and_pruned(tmp_path):
    db, path = _db(tmp_path)
    backups = tmp_path / "backups"
    for day in range(4):
        make_backup(path, backups, NOW + timedelta(days=day), keep=2)

    kept = list_backups(backups)
    assert [p.name for p in kept] == [
        "crm-20260930-040000.sqlite3.gz",
        "crm-20261001-040000.sqlite3.gz",
    ]
    with gzip.open(kept[-1]) as src:
        (tmp_path / "plain.sqlite3").write_bytes(src.read())
    conn = sqlite3.connect(tmp_path / "plain.sqlite3")
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    conn.close()
    db.close()


def test_restore_refuses_while_running_then_replaces_the_database(tmp_path):
    db, path = _db(tmp_path, value=1)
    archive = make_backup(path, tmp_path / "backups", NOW)
    db.run_transaction(lambda tx: tx.set("orders", "N1", {"v": 2}))

    with pytest.raises(StorageError, match="уже открыта"):
        restore_backup(archive, path, NOW)  # the server still runs
    db.close()

    kept = restore_backup(archive, path, NOW)

    assert kept is not None and kept.exists()
    assert SqliteDatabase(path, read_only=True).get("orders", "N1") == {"v": 1}
    assert SqliteDatabase(kept, read_only=True).get("orders", "N1") == {"v": 2}


def test_restore_rejects_a_broken_file(tmp_path):
    db, path = _db(tmp_path)
    db.close()
    bad = tmp_path / "bad.sqlite3.gz"
    with gzip.open(bad, "wb") as out:
        out.write(b"not a database")
    with pytest.raises(StorageError, match="повреждена"):
        restore_backup(bad, path, NOW)
    assert SqliteDatabase(path, read_only=True).get("orders", "N1") == {"v": 1}


def test_next_run_is_at_four_in_seoul():
    assert seconds_until(4, NOW) == 24 * 3600  # exactly 04:00 → tomorrow
    assert seconds_until(4, NOW - timedelta(hours=1)) == 3600


class FakeBot:
    def __init__(self):
        self.documents, self.messages = [], []

    async def send_document(self, chat_id, document, caption=None):
        self.documents.append((chat_id, document.path, caption))

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


async def test_nightly_backup_is_sent_to_the_admins(tmp_path):
    db, path = _db(tmp_path)
    bot = FakeBot()
    job = NightlyBackup(bot, path, tmp_path / "backups", frozenset({1, 2}), now=lambda: NOW)

    archive = await job.run_once()

    assert archive is not None and archive.exists()
    assert [(chat, str(p)) for chat, p, _ in bot.documents] == [
        (1, str(archive)),
        (2, str(archive)),
    ]
    assert "--restore" in bot.documents[0][2]
    db.close()


async def test_failed_backup_is_reported(tmp_path):
    bot = FakeBot()
    job = NightlyBackup(bot, tmp_path / "missing.sqlite3", tmp_path / "b", frozenset({1}))
    assert await job.run_once() is None
    assert "Не удалось" in bot.messages[0][1]
