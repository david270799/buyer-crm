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


def build() -> Router:
    router = Router(name="orders")
    router.message.register(order, Command("order"), HasRole(Role.ADMIN, Role.CLIENT))
    router.message.register(buy, Command("buy"), HasRole(Role.ADMIN))
    router.message.register(cancel, Command("cancel"), HasRole(Role.ADMIN))
    router.message.register(rebuy, Command("rebuy"), HasRole(Role.ADMIN))
    router.message.register(status, Command("status"), HasRole(Role.ADMIN))
    return router
