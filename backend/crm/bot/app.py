import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from crm.bot.access import AccessMiddleware
from crm.bot.handlers import build_router
from crm.config import Settings
from crm.domain.errors import ConfigurationError
from crm.services.container import Services

logger = logging.getLogger(__name__)

ADMIN_COMMANDS = [
    BotCommand(command="buy", description="Выкуп: /buy 5 140000 170000"),
    BotCommand(command="cancel", description="Отмена с возвратом: /cancel 5"),
    BotCommand(command="status", description="Статус: /status warehouse 5 7"),
    BotCommand(command="cargo", description="Отправка: /cargo TRACK 5 10"),
    BotCommand(command="order", description="Карточка заказа"),
    BotCommand(command="shipments", description="Отправки"),
    BotCommand(command="balance", description="Баланс"),
    BotCommand(command="history", description="История баланса"),
    BotCommand(command="deposit", description="Пополнение баланса"),
    BotCommand(command="adjust", description="Корректировка баланса"),
    BotCommand(command="rate", description="Курс KRW/USD"),
    BotCommand(command="help", description="Все команды"),
]

CLIENT_COMMANDS = [
    BotCommand(command="balance", description="Баланс"),
    BotCommand(command="history", description="История баланса"),
    BotCommand(command="order", description="Карточка заказа"),
    BotCommand(command="shipments", description="Отправки"),
    BotCommand(command="help", description="Команды"),
]


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(services: Services, settings: Settings) -> Dispatcher:
    dp = Dispatcher()
    dp["services"] = services
    access = AccessMiddleware(services.roles, settings.allowed_chat_ids)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(build_router())
    return dp


async def run_bot(bot: Bot, services: Services, settings: Settings) -> None:
    """Long polling until cancelled. Always closes the HTTP session."""
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            raise ConfigurationError(
                "BOT_TOKEN недействителен: Telegram отклонил токен. "
                "Скопируйте актуальный токен из @BotFather."
            ) from None
        logger.info("Bot @%s started; admins: %s", me.username, sorted(settings.admin_ids))
        await set_commands(bot, settings.admin_ids)
        dp = create_dispatcher(services, settings)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def set_commands(bot: Bot, admin_ids: frozenset[int]) -> None:
    await bot.set_my_commands(CLIENT_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # noqa: BLE001 - the admin may not have opened the bot yet
            logger.warning(
                "Could not set admin command menu for %s (send /start to the bot)", admin_id
            )
