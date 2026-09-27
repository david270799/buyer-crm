"""One process for everything: HTTP API + Mini App static files + Telegram bot.

    python -m crm.server          # real Firebase from .env
    python -m crm.server --demo   # sample data in memory, Firebase not used;
                                  # open http://localhost:8080 and pick a role

Environment (besides .env.example): PORT (default 8080), HOST (0.0.0.0),
RUN_BOT=0 to serve only the API, WEB_DIST to point at the built Mini App.
"""

import asyncio
import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from crm.config import Settings, load_settings
from crm.domain.errors import ConfigurationError

logger = logging.getLogger(__name__)

# Placeholder Telegram IDs for the browser-only demo (not real accounts).
DEMO_ADMIN_ID = 100_000_001
DEMO_CLIENT_ID = 100_000_002

DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _demo_client_id() -> int:
    raw = os.environ.get("DEMO_CLIENT_TELEGRAM_ID", "").strip()
    if not raw:
        return DEMO_CLIENT_ID
    if not raw.lstrip("-").isdigit():
        raise ConfigurationError("DEMO_CLIENT_TELEGRAM_ID должен быть числом.")
    return int(raw)


def build_app(settings: Settings, demo: bool):
    from crm.api.app import ApiConfig, create_app
    from crm.services.container import build_services

    media_dir = None
    if demo:
        from crm.demo import create_demo_database
        from crm.storage.blobs import LocalBlobStorage

        admin_ids = settings.admin_ids or frozenset({DEMO_ADMIN_ID})
        client_id = _demo_client_id()
        media_dir = Path(tempfile.mkdtemp(prefix="crm-demo-media-"))
        blobs = LocalBlobStorage(media_dir)
        db = create_demo_database(client_id, blob_storage=blobs)
        logger.warning("ДЕМО-РЕЖИМ: данные в памяти, Firebase не используется.")
    else:
        from crm.firebase import create_blob_storage, create_database

        admin_ids = settings.admin_ids
        client_id = None
        db = create_database(settings)
        blobs = create_blob_storage(settings)
        if blobs is None:
            logger.warning("FIREBASE_STORAGE_BUCKET не задан — загрузка фото отключена.")

    services = build_services(db, admin_ids, blob_storage=blobs)
    web_dist = Path(os.environ.get("WEB_DIST") or DEFAULT_WEB_DIST)
    if not (web_dist / "index.html").is_file():
        logger.warning("Mini App не собран (%s) — работает только API. См. web/README.", web_dist)

    run_bot = bool(settings.bot_token) and os.environ.get("RUN_BOT", "1") != "0"
    lifespan = _bot_lifespan(services, settings) if run_bot else None
    config = ApiConfig(
        bot_token=settings.bot_token,
        init_data_max_age_seconds=settings.init_data_max_age_hours * 3600,
        web_origins=settings.web_origins,
        demo=demo,
        demo_admin_id=min(admin_ids) if demo else None,
        demo_client_id=client_id,
        static_dir=web_dist,
        media_dir=media_dir,
    )
    return create_app(services, config, lifespan=lifespan)


def _bot_lifespan(services, settings: Settings):
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        from crm.bot.app import create_bot, run_bot

        task = asyncio.create_task(
            run_bot(create_bot(settings.bot_token), services, settings, handle_signals=False)
        )
        task.add_done_callback(_report_bot_exit)
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return lifespan


def _report_bot_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if isinstance(exc, ConfigurationError):
        logger.error("Бот остановлен: %s (API продолжает работать)", exc.user_message)
    elif exc is not None:
        logger.error("Бот остановлен из-за ошибки (API продолжает работать)", exc_info=exc)


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    demo = "--demo" in sys.argv[1:]
    try:
        settings = load_settings(require_bot=not demo)
        logging.getLogger().setLevel(settings.log_level)
        app = build_app(settings, demo)
    except ConfigurationError as exc:
        print(f"Ошибка конфигурации: {exc.user_message}", file=sys.stderr)
        sys.exit(2)

    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("CRM: http://%s:%s", "localhost" if host == "0.0.0.0" else host, settings.port)
    uvicorn.run(app, host=host, port=settings.port, proxy_headers=True, log_level="info")


if __name__ == "__main__":
    main()
