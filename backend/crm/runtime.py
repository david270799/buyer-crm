"""Storage chosen by configuration: SQLite on this server (default) or Firebase."""

import logging

from crm.config import Settings
from crm.storage import Database
from crm.storage.blobs import BlobStorage, LocalBlobStorage

logger = logging.getLogger(__name__)


def create_database(settings: Settings) -> Database:
    if settings.storage == "firestore":
        from crm.firebase import create_database as create_firestore

        return create_firestore(settings)
    from crm.storage.sqlite import SqliteDatabase

    logger.info("SQLite database: %s", settings.database_path)
    return SqliteDatabase(settings.database_path)


def open_read_only(settings: Settings) -> Database:
    """For tools (doctor) that run next to the server without taking its lock."""
    if settings.storage == "firestore":
        return create_database(settings)
    from crm.storage.sqlite import SqliteDatabase

    return SqliteDatabase(settings.database_path, read_only=True)


def create_blob_storage(settings: Settings) -> BlobStorage | None:
    if settings.storage == "firestore":
        from crm.firebase import create_blob_storage as create_firebase_storage

        return create_firebase_storage(settings)
    return LocalBlobStorage(settings.media_dir)


def media_dir(settings: Settings):
    """Directory served under /media, or None when photos live in Firebase."""
    return settings.media_dir if settings.storage == "sqlite" else None
