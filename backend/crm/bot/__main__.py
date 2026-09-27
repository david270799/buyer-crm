"""Run the bot with long polling: `python -m crm.bot` (from the backend/ directory)."""

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramNetworkError
from dotenv import find_dotenv, load_dotenv

from crm.config import load_settings
from crm.domain.errors import ConfigurationError


async def _main() -> None:
    from crm.bot.app import create_bot, run_bot
    from crm.firebase import create_database
    from crm.services.container import build_services

    settings = load_settings()
    logging.getLogger().setLevel(settings.log_level)
    services = build_services(create_database(settings), settings.admin_ids)
    await run_bot(create_bot(settings.bot_token), services, settings)


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(_main())
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
