"""/topic: what a topic of the admin's group is for (crm.services.admin_group)."""

import asyncio

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from crm.bot import formatting as fmt
from crm.bot.access import HasRole
from crm.bot.admin_group import thread_of, topic_name
from crm.domain.enums import Role
from crm.domain.errors import CRMError
from crm.services.admin_group import (
    KINDS,
    NOTIFICATIONS,
    SHOWCASE,
    WAREHOUSE,
    AdminGroup,
    kind_from_text,
)
from crm.services.common import Actor
from crm.services.container import Services

WHAT = {
    WAREHOUSE: (
        "🏠 Эта тема — <b>«Склад»</b>.\n"
        "Присылайте сюда фото пришедших товаров: бот спросит, какой это заказ, сверит размер, "
        "поставит «На складе» и напишет отзыв. Подпись «N5» — сразу к заказу N5."
    ),
    SHOWCASE: (
        "🛍 Эта тема — <b>«Витрина»</b>.\n"
        "Присылайте ссылку на товар — бот прочитает цену и размеры. Или скриншот из магазина — "
        "бот найдёт модель и фото, цена будет как на скриншоте, размеры впишете в «Одобрении»."
    ),
    NOTIFICATIONS: (
        "🔔 Эта тема — <b>«Уведомления»</b>.\n"
        "Сюда бот пишет всё, что раньше присылал вам в личку: вопросы по новым заказам, "
        "уведомления CRM, «клиент получил не всё»."
    ),
}

USAGE = (
    "Напишите команду внутри темы своей группы: <code>/topic склад</code>, "
    "<code>/topic витрина</code> или <code>/topic уведомления</code> "
    "(или просто /topic — бот поймёт по названию темы)."
)


def status_text(group: AdminGroup) -> str:
    if group.chat_id is None:
        return "Группа с темами не настроена: всё приходит в личку.\n" + USAGE
    lines = [f"Группа: <b>{fmt.e(group.title or group.chat_id)}</b>"]
    for kind, name in KINDS.items():
        mark = "✅" if group.topic(kind) is not None else "—"
        lines.append(f"{mark} «{name}»")
    missing = [name for kind, name in KINDS.items() if group.topic(kind) is None]
    if missing:
        lines.append("Не привязаны: " + ", ".join(f"«{m}»" for m in missing) + ". " + USAGE)
    return "\n".join(lines)


def build(services: Services) -> Router:
    router = Router(name="topics")

    async def on_topic(message: Message, command: CommandObject, actor: Actor) -> None:
        if services.admin_group is None:
            return
        arg = (command.args or "").strip()
        if message.chat.type == ChatType.PRIVATE:
            if arg.lower() in ("off", "выкл", "нет"):
                group = await asyncio.to_thread(services.admin_group.unbind, actor)
                await message.answer("Группа отвязана: всё снова приходит в личку.")
                return
            group = await asyncio.to_thread(services.admin_group.current)
            await message.answer(status_text(group) + "\n\nОтвязать группу: /topic off")
            return
        thread = thread_of(message)
        kind = kind_from_text(arg) or kind_from_text(topic_name(message))
        if thread is None or kind is None:
            await message.reply(USAGE)
            return
        try:
            group = await asyncio.to_thread(
                services.admin_group.bind,
                actor,
                message.chat.id,
                message.chat.title,
                thread,
                kind,
            )
        except CRMError as exc:
            await message.reply(f"❌ {fmt.e(exc.user_message)}")
            return
        missing = [name for k, name in KINDS.items() if group.topic(k) is None]
        tail = (
            "\n\nОсталось привязать: " + ", ".join(f"«{m}»" for m in missing) + "."
            if missing
            else "\n\nВсе три темы привязаны ✅"
        )
        await message.reply(WHAT[kind] + tail)

    router.message.register(on_topic, Command("topic"), HasRole(Role.ADMIN))
    return router
