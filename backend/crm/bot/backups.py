"""Nightly database backup, also sent to the admins in Telegram (off-site copy)."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from crm.backup import make_backup
from crm.domain.timeutil import BUSINESS_TZ, format_datetime

logger = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 45 * 1024 * 1024  # bots may upload up to 50 MB


def seconds_until(hour: int, now: datetime) -> float:
    """Seconds from `now` to the next `hour`:00 in Seoul."""
    local = now.astimezone(BUSINESS_TZ)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return (target - local).total_seconds()


class NightlyBackup:
    def __init__(
        self,
        bot: Bot,
        db_path: Path,
        backup_dir: Path,
        admin_ids: frozenset[int],
        *,
        keep: int = 14,
        send: bool = True,
        hour: int = 4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._bot = bot
        self._db_path = db_path
        self._backup_dir = backup_dir
        self._admin_ids = admin_ids
        self._keep = keep
        self._send = send
        self._hour = hour
        self._now = now

    async def run(self) -> None:
        while True:
            await asyncio.sleep(seconds_until(self._hour, self._now()))
            await self.run_once()

    async def run_once(self) -> Path | None:
        moment = self._now()
        try:
            archive = await asyncio.to_thread(
                make_backup, self._db_path, self._backup_dir, moment, self._keep
            )
        except Exception:  # noqa: BLE001 - tell the admins, try again tomorrow
            logger.exception("Nightly backup failed")
            await self._tell("⚠️ Не удалось сделать ночную копию базы CRM. Подробности в логе.")
            return None
        logger.info("Backup %s (%s KB)", archive.name, archive.stat().st_size // 1024)
        if self._send:
            await self._send_file(archive, moment)
        return archive

    async def _send_file(self, archive: Path, moment: datetime) -> None:
        if archive.stat().st_size > TELEGRAM_FILE_LIMIT:
            await self._tell(
                f"🗄 Копия базы сделана ({archive.name}), но слишком большая для Telegram."
            )
            return
        caption = (
            f"🗄 Копия базы CRM на {format_datetime(moment)}.\n"
            "Храните её: из неё восстанавливаются все заказы, деньги и история "
            "(команда python -m crm.tools.backup --restore). Фото в копию не входят."
        )
        for admin_id in sorted(self._admin_ids):
            with contextlib.suppress(Exception):
                await self._bot.send_document(admin_id, FSInputFile(archive), caption=caption)

    async def _tell(self, text: str) -> None:
        for admin_id in sorted(self._admin_ids):
            with contextlib.suppress(Exception):
                await self._bot.send_message(admin_id, text)
