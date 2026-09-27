import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from crm.bot import formatting as fmt
from crm.bot import parsing
from crm.bot.access import HasRole
from crm.bot.handlers.reply import answer
from crm.domain.enums import Role
from crm.domain.errors import ValidationError
from crm.services.common import Actor
from crm.services.container import Services


async def cargo(message: Message, command: CommandObject, services: Services, actor: Actor) -> None:
    tracking_code, order_ids = parsing.parse_cargo(command.args)
    result = await asyncio.to_thread(
        services.shipments.ship_orders, actor, order_ids, tracking_code
    )
    await answer(message, fmt.cargo_result(result))


async def shipments(message: Message, services: Services, actor: Actor) -> None:
    items = await asyncio.to_thread(services.shipments.list_shipments, actor)
    await answer(message, fmt.shipments_list(items))


async def shipment(
    message: Message, command: CommandObject, services: Services, actor: Actor
) -> None:
    shipment_id = (command.args or "").strip()
    if not shipment_id:
        raise ValidationError("Формат: /shipment SHP-2026-001")
    found, orders = await asyncio.to_thread(services.shipments.get_shipment, actor, shipment_id)
    await answer(message, fmt.shipment_details(found, orders))


def build() -> Router:
    router = Router(name="shipments")
    router.message.register(cargo, Command("cargo"), HasRole(Role.ADMIN))
    router.message.register(shipments, Command("shipments"), HasRole(Role.ADMIN, Role.CLIENT))
    router.message.register(shipment, Command("shipment"), HasRole(Role.ADMIN, Role.CLIENT))
    return router
