from aiogram import Router

from crm.bot.handlers import (
    arrival,
    common,
    errors,
    fallback,
    finance,
    intake,
    orders,
    shipments,
    showcase,
)
from crm.config import Settings
from crm.services.container import Services


def build_router(services: Services, settings: Settings) -> Router:
    """Fresh router tree per Dispatcher (aiogram routers attach to one parent only)."""
    root = Router(name="root")
    # Order matters: the fallback must stay last.
    root.include_routers(
        common.build(),
        orders.build(),
        shipments.build(),
        finance.build(),
        arrival.build(services, settings),  # before the intake: «N5» photos are arrivals
        intake.build(services, settings),
        showcase.build(services, settings),  # a shop link from the admin → draft
        fallback.build(),
    )
    root.errors.register(errors.on_error)
    return root
