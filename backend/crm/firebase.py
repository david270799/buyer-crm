"""Firebase / Firestore initialisation.

Credential lookup order:
1. FIRESTORE_EMULATOR_HOST set  -> local emulator, no credentials needed;
2. FIREBASE_CREDENTIALS         -> path to a service-account JSON file;
3. FIREBASE_CREDENTIALS_JSON    -> the same JSON inline (for hosting platforms);
4. Application Default Credentials (Cloud Run / GCE / `gcloud auth`).
"""

import json
import logging
import os
from pathlib import Path

from crm.config import Settings
from crm.domain.errors import ConfigurationError
from crm.storage.firestore import FirestoreDatabase

logger = logging.getLogger(__name__)


# Lists, filters and search in the Mini App read the whole `orders`
# collection; this keeps that to at most one full read per minute.
ORDERS_SCAN_CACHE_SECONDS = 60


def create_database(settings: Settings) -> FirestoreDatabase:
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        from google.cloud.firestore_v1 import Client

        project = settings.firebase_project_id or "demo-buyer-crm"
        logger.warning(
            "Using Firestore EMULATOR at %s (project %s)",
            os.environ["FIRESTORE_EMULATOR_HOST"],
            project,
        )
        return FirestoreDatabase(
            Client(project=project),
            scan_cache_seconds=ORDERS_SCAN_CACHE_SECONDS,
            cached_collections=("orders",),
        )

    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        app = firebase_admin.get_app()
    except ValueError:
        options: dict[str, str] = {}
        if settings.firebase_project_id:
            options["projectId"] = settings.firebase_project_id
        if settings.firebase_storage_bucket:
            options["storageBucket"] = settings.firebase_storage_bucket
        app = firebase_admin.initialize_app(_credentials(settings, credentials), options or None)
    return FirestoreDatabase(
        firestore.client(app),
        scan_cache_seconds=ORDERS_SCAN_CACHE_SECONDS,
        cached_collections=("orders",),
    )


def _credentials(settings: Settings, credentials):
    if settings.firebase_credentials_path:
        path = Path(settings.firebase_credentials_path).expanduser()
        if not path.is_file():
            raise ConfigurationError(f"Файл сервисного аккаунта Firebase не найден: {path}")
        return credentials.Certificate(str(path))
    if settings.firebase_credentials_json:
        try:
            info = json.loads(settings.firebase_credentials_json)
        except json.JSONDecodeError:
            raise ConfigurationError(
                "FIREBASE_CREDENTIALS_JSON содержит некорректный JSON."
            ) from None
        return credentials.Certificate(info)
    try:
        return credentials.ApplicationDefault()
    except Exception:  # noqa: BLE001 - google-auth raises several types here
        raise ConfigurationError(
            "Не найдены учётные данные Firebase. Укажите FIREBASE_CREDENTIALS (путь к JSON "
            "сервисного аккаунта) или FIREBASE_CREDENTIALS_JSON."
        ) from None


def create_blob_storage(settings: Settings):
    """Firebase Storage for photos, or None when no bucket is configured."""
    if not settings.firebase_storage_bucket:
        return None
    import firebase_admin
    from firebase_admin import storage

    from crm.storage.blobs import FirebaseBlobStorage

    app = firebase_admin.get_app()  # initialised by create_database
    return FirebaseBlobStorage(storage.bucket(settings.firebase_storage_bucket, app=app))
