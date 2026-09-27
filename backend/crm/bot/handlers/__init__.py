from aiogram import Router

from crm.bot.handlers import common, errors, fallback, finance, intake, orders, shipments
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
        intake.build(services, settings),
        fallback.build(),
    )
    root.errors.register(errors.on_error)
    return root
