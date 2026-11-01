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
    def __init__(
        self,
        roles: RoleResolver,
        allowed_chat_ids: frozenset[int],
        allowed: Callable[[], frozenset[int]] | None = None,
        admin_chat: Callable[[], int | None] | None = None,
    ):
        self._roles = roles
        self._allowed_chat_ids = allowed_chat_ids
        # Groups added with /setgroup (read on each update, the data is in memory).
        self._allowed = allowed
        # The admin's group with topics (crm.services.admin_group).
        self._admin_chat = admin_chat

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")
        allowed = self._allowed() if self._allowed else self._allowed_chat_ids
        admin_chat = self._admin_chat() if self._admin_chat else None
        if (
            chat is not None
            and chat.type != ChatType.PRIVATE
            and allowed
            and chat.id not in allowed
            and chat.id != admin_chat
            and not _is_setgroup(event)
        ):
            logger.info("Ignoring update from non-allowed chat %s", chat.id)
            return None

        role = await asyncio.to_thread(self._roles.resolve, user.id) if user else None
        data["role"] = role
        data["actor"] = Actor.telegram(user.id, role) if user and role else None
        data["audience"] = audience_for(role, chat, admin_chat)
        return await handler(event, data)


def _is_setgroup(event: TelegramObject) -> bool:
    """/setgroup and /topic must reach their handlers in a group that is not
    allowed yet (the handlers themselves accept them only from an admin)."""
    text = getattr(event, "text", None) or ""
    return text.split("@", 1)[0].split(" ", 1)[0] in ("/setgroup", "/topic")


def audience_for(role: Role | None, chat: Chat | None, admin_chat: int | None = None) -> Role:
    """Whose visibility rules apply to a reply.

    Everyone in a chat sees the bot's reply, and the client is a member of
    the orders group, so outside a private chat replies are always rendered
    for the CLIENT — even when the admin asked. The admin's own group with
    topics is the exception: only admins are there.
    """
    if role is Role.ADMIN and chat is not None:
        if chat.type == ChatType.PRIVATE or (admin_chat is not None and chat.id == admin_chat):
            return Role.ADMIN
    return Role.CLIENT


class HasRole(Filter):
    def __init__(self, *roles: Role):
        self._roles = frozenset(roles)

    async def __call__(self, event: TelegramObject, role: Role | None = None) -> bool:
        return role in self._roles
