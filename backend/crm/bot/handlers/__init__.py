from aiogram import Router

from crm.bot.handlers import common, errors, fallback, finance, orders, shipments


def build_router() -> Router:
    """Fresh router tree per Dispatcher (aiogram routers attach to one parent only)."""
    root = Router(name="root")
    # Order matters: the fallback must stay last.
    root.include_routers(
        common.build(), orders.build(), shipments.build(), finance.build(), fallback.build()
    )
    root.errors.register(errors.on_error)
    return root
