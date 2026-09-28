import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonWebApp,
    WebAppInfo,
)

from crm.bot.access import AccessMiddleware
from crm.bot.backups import NightlyBackup
from crm.bot.handlers import build_router
from crm.bot.notifier import TelegramNotifier
from crm.config import Settings
from crm.domain.errors import ConfigurationError
from crm.services.container import Services
from crm.storage import Database
from crm.storage.sqlite import SqliteDatabase

logger = logging.getLogger(__name__)

ADMIN_COMMANDS = [
    BotCommand(command="buy", description="Выкуп: /buy 5 140000 170000"),
    BotCommand(command="cancel", description="Отмена с возвратом: /cancel 5"),
    BotCommand(command="rebuy", description="Перезаказ: /rebuy 5 150000 185000"),
    BotCommand(command="status", description="Статус: /status warehouse 5 7"),
    BotCommand(command="delete", description="Удалить заказы: /delete 1-5"),
    BotCommand(command="cargo", description="Отправка: /cargo TRACK 5 10"),
    BotCommand(command="shipcost", description="Стоимость доставки: /shipcost 1 95000"),
    BotCommand(command="order", description="Карточка заказа"),
    BotCommand(command="shipments", description="Отправки"),
    BotCommand(command="balance", description="Баланс"),
    BotCommand(command="history", description="История баланса"),
    BotCommand(command="deposit", description="Пополнение баланса"),
    BotCommand(command="adjust", description="Корректировка баланса"),
    BotCommand(command="rate", description="Курс KRW/USD"),
    BotCommand(command="add", description="Принять фото как заказ (ответом на фото)"),
    BotCommand(command="setclient", description="Указать клиента (ответом на его сообщение)"),
    BotCommand(command="notify", description="Уведомления в личку"),
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
    dp["settings"] = settings
    access = AccessMiddleware(services.roles, settings.allowed_chat_ids)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(build_router(services, settings))
    return dp


async def run_bot(
    bot: Bot,
    services: Services,
    settings: Settings,
    *,
    handle_signals: bool = True,
    database: Database | None = None,
) -> None:
    """Long polling until cancelled. Always closes the HTTP session.

    `handle_signals=False` when embedded in the web server, which owns signals.
    With a SQLite `database` the bot also makes the nightly backup.
    """
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            raise ConfigurationError(
                "BOT_TOKEN недействителен: Telegram отклонил токен. "
                "Скопируйте актуальный токен из @BotFather."
            ) from None
        logger.info("Bot @%s started; admins: %s", me.username, sorted(settings.admin_ids))
        if not settings.admin_ids:
            logger.warning(
                "ADMIN_TELEGRAM_IDS не задан: доступа нет ни у кого. Напишите боту /whoami, "
                "впишите свой ID в .env (ADMIN_TELEGRAM_IDS=...) и перезапустите."
            )
        if not me.can_read_all_group_messages:
            logger.warning(
                "Privacy mode is on: in groups the bot sees order photos only if it is a group "
                "admin. Turn it off in @BotFather: /setprivacy → Disable, then re-add the bot."
            )
        if services.recognizer is None:
            logger.warning("GEMINI_API_KEY is not set: orders are accepted without recognition.")
        await set_commands(bot, settings.admin_ids)
        if settings.mini_app_url:
            await set_menu_button(bot, settings.mini_app_url)
        dp = create_dispatcher(services, settings)
        notifier = TelegramNotifier(bot, services.notifications, settings.mini_app_url)
        notifier_task = asyncio.create_task(notifier.run(), name="telegram-notifier")
        notifier_task.add_done_callback(_report_notifier_exit)
        background = [notifier_task]
        if isinstance(database, SqliteDatabase) and not database.read_only:
            nightly = NightlyBackup(
                bot,
                database.path,
                settings.backup_dir,
                settings.admin_ids,
                keep=settings.backup_keep,
                send=settings.backup_to_telegram,
            )
            backup_task = asyncio.create_task(nightly.run(), name="nightly-backup")
            backup_task.add_done_callback(_report_notifier_exit)
            background.append(backup_task)
        try:
            await dp.start_polling(
                bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=handle_signals
            )
        finally:
            for task in background:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        await bot.session.close()


def _report_notifier_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Background task %s stopped", task.get_name(), exc_info=task.exception())


async def set_commands(bot: Bot, admin_ids: frozenset[int]) -> None:
    await bot.set_my_commands(CLIENT_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # noqa: BLE001 - the admin may not have opened the bot yet
            logger.warning(
                "Could not set admin command menu for %s (send /start to the bot)", admin_id
            )


async def set_menu_button(bot: Bot, url: str) -> None:
    """The «CRM» button next to the message field in private chats opens the Mini App."""
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="CRM", web_app=WebAppInfo(url=url))
        )
    except Exception:  # noqa: BLE001 - not fatal, the bot keeps working
        logger.warning("Could not set the Mini App menu button", exc_info=True)
