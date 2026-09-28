"""Run the bot with long polling (from the backend/ directory).

python -m crm.bot           # real Firebase from .env
python -m crm.bot --demo    # sample data in memory, Firebase not used
"""

import asyncio
import logging
import os
import sys

from aiogram.exceptions import TelegramNetworkError
from dotenv import find_dotenv, load_dotenv

from crm.config import load_settings
from crm.domain.errors import ConfigurationError


def _demo_client_id() -> int | None:
    raw = os.environ.get("DEMO_CLIENT_TELEGRAM_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigurationError(
            f"DEMO_CLIENT_TELEGRAM_ID: «{raw}» не является числовым Telegram ID."
        ) from None


async def _main(demo: bool) -> None:
    from crm.bot.app import create_bot, run_bot
    from crm.services.container import build_services

    settings = load_settings()
    logging.getLogger().setLevel(settings.log_level)
    if demo:
        from crm.demo import create_demo_database

        db = create_demo_database(_demo_client_id())
        logging.warning(
            "ДЕМО-РЕЖИМ: данные в памяти, Firebase не используется, "
            "после перезапуска всё начнётся заново."
        )
        blobs = None
    else:
        from crm.runtime import create_blob_storage, create_database

        db = create_database(settings)
        blobs = create_blob_storage(settings)
    from crm.services.recognition import create_recognizer

    recognizer = create_recognizer(settings.gemini_api_key, settings.gemini_model)
    services = build_services(db, settings.admin_ids, blob_storage=blobs, recognizer=recognizer)
    await run_bot(create_bot(settings.bot_token), services, settings, database=db)


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(_main(demo="--demo" in sys.argv[1:]))
    except ConfigurationError as exc:
        print(f"Ошибка конфигурации: {exc.user_message}", file=sys.stderr)
        sys.exit(2)
    except TelegramNetworkError as exc:
        print(f"Нет связи с Telegram: {exc.message}", file=sys.stderr)
        sys.exit(3)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
