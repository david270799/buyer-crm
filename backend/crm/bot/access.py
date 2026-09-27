"""Who is talking to the bot.

`AccessMiddleware` runs before filters and puts `role` (Role | None) and
`actor` (Actor | None) into handler data. `HasRole` filters on it. Handlers
for admin commands are registered with `HasRole(Role.ADMIN)`, so a client or
a stranger never reaches them; services check the role again anyway.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.filters import Filter
from aiogram.types import Chat, TelegramObject, User

from crm.domain.enums import Role
from crm.services.auth import RoleResolver
from crm.services.common import Actor

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, roles: RoleResolver, allowed_chat_ids: frozenset[int]):
        self._roles = roles
        self._allowed_chat_ids = allowed_chat_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")
        if (
            chat is not None
            and chat.type != ChatType.PRIVATE
            and self._allowed_chat_ids
            and chat.id not in self._allowed_chat_ids
        ):
            logger.info("Ignoring update from non-allowed chat %s", chat.id)
            return None

        role = await asyncio.to_thread(self._roles.resolve, user.id) if user else None
        data["role"] = role
        data["actor"] = Actor.telegram(user.id, role) if user and role else None
        data["audience"] = audience_for(role, chat)
        return await handler(event, data)


def audience_for(role: Role | None, chat: Chat | None) -> Role:
    """Whose visibility rules apply to a reply.

    Everyone in a chat sees the bot's reply, and the client is a member of
    the orders group, so outside a private chat replies are always rendered
    for the CLIENT — even when the admin asked.
    """
    if role is Role.ADMIN and chat is not None and chat.type == ChatType.PRIVATE:
        return Role.ADMIN
    return Role.CLIENT


class HasRole(Filter):
    def __init__(self, *roles: Role):
        self._roles = frozenset(roles)

    async def __call__(self, event: TelegramObject, role: Role | None = None) -> bool:
        return role in self._roles
