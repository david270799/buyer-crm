import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from crm.bot import formatting as fmt
from crm.bot import parsing
from crm.bot.access import HasRole
from crm.bot.handlers.reply import answer
from crm.domain.enums import Role
from crm.services.common import Actor
from crm.services.container import Services


def _idempotency_key(message: Message) -> str:
    # The same Telegram message delivered twice must not move money twice.
    return f"tg{message.chat.id}_{message.message_id}"


async def balance(message: Message, services: Services, actor: Actor) -> None:
    view = await asyncio.to_thread(services.finance.get_balance, actor)
    await answer(message, fmt.balance(view))


async def history(message: Message, services: Services, actor: Actor) -> None:
    entries = await asyncio.to_thread(services.finance.history, actor, 20)
    await answer(message, fmt.history(entries))


async def deposit(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    amount, comment = parsing.parse_amount_with_comment(
        command.args, parsing.DEPOSIT_USAGE, allow_negative=False
    )
    result = await asyncio.to_thread(
        services.finance.deposit, actor, amount, comment, _idempotency_key(message)
    )
    await answer(message, fmt.ledger_result(result))


async def adjust(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    amount, comment = parsing.parse_amount_with_comment(
        command.args, parsing.ADJUST_USAGE, allow_negative=True
    )
    result = await asyncio.to_thread(
        services.finance.adjust, actor, amount, comment or "", _idempotency_key(message)
    )
    await answer(message, fmt.ledger_result(result))


async def rate(message: Message, command: CommandObject, services: Services, actor: Actor) -> None:
    new_rate = parsing.parse_rate_command(command.args)
    if new_rate is None:
        current = await asyncio.to_thread(services.finance.get_settings, actor)
        await answer(message, fmt.rate_current(current.krw_per_usd))
        return
    updated = await asyncio.to_thread(services.finance.set_rate, actor, new_rate)
    await answer(message, fmt.rate_set(updated.krw_per_usd))


async def notify(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    changes = parsing.parse_notify(command.args)
    notifications = services.notifications
    if changes:
        current = await asyncio.to_thread(notifications.update_settings, actor, **changes)
    else:
        current = await asyncio.to_thread(notifications.get_settings, actor)
    has_telegram = await asyncio.to_thread(notifications.client_has_telegram, actor)
    await answer(message, fmt.notify_settings(current, has_telegram))


def build() -> Router:
    router = Router(name="finance")
    router.message.register(balance, Command("balance"), HasRole(Role.ADMIN, Role.CLIENT))
    router.message.register(history, Command("history"), HasRole(Role.ADMIN, Role.CLIENT))
    router.message.register(deposit, Command("deposit"), HasRole(Role.ADMIN))
    router.message.register(adjust, Command("adjust"), HasRole(Role.ADMIN))
    router.message.register(rate, Command("rate"), HasRole(Role.ADMIN))
    router.message.register(notify, Command("notify"), HasRole(Role.ADMIN))
    return router
