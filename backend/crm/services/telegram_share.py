"""Hand a picture to the admin's own Telegram so they can send it on.

The CRM never writes to the client here (the owner, 23.10.2026: «I send it
myself»). The picture goes to the admin's chat with the bot only to get a
Telegram file id; with it the bot prepares an inline message, and the Mini
App opens Telegram's chat picker (`WebApp.shareMessage`). Without that
picker (old Telegram) the picture stays in the chat to forward by hand.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from crm.domain.errors import CRMError

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class ShareError(CRMError):
    pass


class TelegramShare:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self._token = token
        self._transport = transport

    def _call(self, client: httpx.Client, method: str, **kwargs) -> dict:
        try:
            response = client.post(API.format(token=self._token, method=method), **kwargs)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ShareError("Telegram не ответил, попробуйте ещё раз.") from exc
        if not body.get("ok"):
            logger.warning("Telegram %s failed: %s", method, body.get("description"))
            raise ShareError(f"Telegram отказал: {body.get('description', 'ошибка')}")
        return body["result"]

    def share_photo(self, user_id: int, image: bytes, *, picker: bool) -> str | None:
        """Prepared message id for the chat picker, or None when the picture
        was left in the admin's chat with the bot to forward."""
        with httpx.Client(timeout=30, transport=self._transport) as client:
            sent = self._call(
                client,
                "sendPhoto",
                data={"chat_id": str(user_id), "disable_notification": "true"},
                files={"photo": ("crm.png", image, "image/png")},
            )
            if not picker:
                return None
            try:
                prepared = self._call(
                    client,
                    "savePreparedInlineMessage",
                    json={
                        "user_id": user_id,
                        "result": {
                            "type": "photo",
                            "id": uuid.uuid4().hex,
                            "photo_file_id": sent["photo"][-1]["file_id"],
                        },
                        "allow_user_chats": True,
                        "allow_group_chats": True,
                        "allow_channel_chats": True,
                    },
                )
            except ShareError:
                return None  # the picture is in the chat: forward it from there
            try:
                self._call(
                    client,
                    "deleteMessage",
                    json={"chat_id": user_id, "message_id": sent["message_id"]},
                )
            except ShareError:
                pass  # a spare copy in the admin's own chat does no harm
            return prepared["id"]
