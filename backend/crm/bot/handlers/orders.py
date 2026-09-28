import asyncio
import contextlib

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from crm.bot import formatting as fmt
from crm.bot import parsing
from crm.bot.access import HasRole
from crm.bot.handlers.errors import user_text
from crm.bot.handlers.reply import answer, answer_privately
from crm.domain.enums import Role
from crm.domain.errors import CRMError, ValidationError
from crm.services.common import Actor
from crm.services.container import Services


async def order(
    message: Message, command: CommandObject, services: Services, actor: Actor, audience: Role
) -> None:
    order_id = parsing.parse_single_order(command.args, parsing.ORDER_USAGE)
    found = await asyncio.to_thread(services.orders.get_order, actor, order_id)
    await answer(message, fmt.order_details(found, audience))


async def buy(
    message: Message, command: CommandObject, services: Services, actor: Actor, audience: Role
) -> None:
    order_id, purchase_price, client_price = parsing.parse_buy(command.args)
    result = await asyncio.to_thread(
        services.orders.buy, actor, order_id, purchase_price, client_price
    )
    await answer(message, fmt.buy_result(result, audience))


async def rebuy(
    message: Message, command: CommandObject, services: Services, actor: Actor, audience: Role
) -> None:
    order_id, purchase, price, link, reason = parsing.parse_rebuy(command.args)
    extra = {"source_url": link} if link else {}
    result = await asyncio.to_thread(
        lambda: services.orders.rebuy(actor, order_id, purchase, price, reason=reason, **extra)
    )
    await answer(message, fmt.rebuy_result(result, audience))


async def cancel(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    order_id = parsing.parse_single_order(command.args, parsing.CANCEL_USAGE)
    result = await asyncio.to_thread(services.orders.cancel, actor, order_id)
    await answer(message, fmt.cancel_result(result))


async def status(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    new_status, order_ids = parsing.parse_status_command(command.args)
    result = await asyncio.to_thread(services.orders.set_status, actor, order_ids, new_status)
    await answer(message, fmt.status_result(new_status, result))


DELETE_PREFIX = "del:"
DELETE_CANCEL = "del-cancel"
_CALLBACK_LIMIT = 64  # bytes, Telegram's limit for callback data


def delete_keyboard(order_ids: list[str]) -> InlineKeyboardMarkup:
    data = DELETE_PREFIX + parsing.compact_order_ids(order_ids)
    if len(data.encode()) > _CALLBACK_LIMIT:
        raise ValidationError(
            "Слишком много разрозненных номеров для одной команды. Удалите их в несколько "
            "приёмов или диапазонами, например /delete 1-20."
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🗑 Удалить ({len(order_ids)})", callback_data=data),
                InlineKeyboardButton(text="Отмена", callback_data=DELETE_CANCEL),
            ]
        ]
    )


async def delete(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    """Asks first: deletion cannot be undone. The answer goes to the admin's
    private chat, so nothing is written in the client's group."""
    order_ids = parsing.parse_order_list(command.args, parsing.DELETE_USAGE)
    preview = await asyncio.to_thread(services.orders.preview_delete, actor, order_ids)
    text = fmt.delete_preview(preview)
    if not preview.orders:
        await answer_privately(message, text)
        return
    markup = delete_keyboard([o.id for o in preview.orders])
    if message.chat.type == ChatType.PRIVATE or message.bot is None or message.from_user is None:
        await message.answer(text, reply_markup=markup)
        return
    await message.bot.send_message(message.from_user.id, text, reply_markup=markup)
    with contextlib.suppress(Exception):  # no right to delete in the group: fine
        await message.delete()


async def delete_confirmed(query: CallbackQuery, services: Services, actor: Actor) -> None:
    order_ids = parsing.expand_order_ids((query.data or "")[len(DELETE_PREFIX) :])
    try:
        result = await asyncio.to_thread(services.orders.delete_orders, actor, order_ids)
        text = fmt.delete_result(result)
    except CRMError as exc:
        text = user_text(exc)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.edit_text(text, reply_markup=None)


async def delete_cancelled(query: CallbackQuery) -> None:
    await query.answer("Удаление отменено")
    if isinstance(query.message, Message):
        await query.message.edit_text(
            "Удаление отменено — ничего не изменилось.", reply_markup=None
        )


def build() -> Router:
    router = Router(name="orders")
    router.message.register(order, Command("order"), HasRole(Role.ADMIN, Role.CLIENT))
    router.message.register(buy, Command("buy"), HasRole(Role.ADMIN))
    router.message.register(cancel, Command("cancel"), HasRole(Role.ADMIN))
    router.message.register(rebuy, Command("rebuy"), HasRole(Role.ADMIN))
    router.message.register(status, Command("status"), HasRole(Role.ADMIN))
    router.message.register(delete, Command("delete"), HasRole(Role.ADMIN))
    router.callback_query.register(
        delete_confirmed, F.data.startswith(DELETE_PREFIX), HasRole(Role.ADMIN)
    )
    router.callback_query.register(delete_cancelled, F.data == DELETE_CANCEL, HasRole(Role.ADMIN))
    return router
