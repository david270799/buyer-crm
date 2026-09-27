"""Configuration from environment variables (a local `.env` is loaded by entrypoints).

Secrets (bot token, Firebase service account, Gemini key) live only in the
environment or in files outside git. See `.env.example`.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from crm.domain.errors import ConfigurationError


@dataclass(frozen=True)
class Settings:
    bot_token: str | None
    admin_ids: frozenset[int]
    allowed_chat_ids: frozenset[int]
    firebase_project_id: str | None
    firebase_credentials_path: str | None
    firebase_credentials_json: str | None
    firebase_storage_bucket: str | None
    gemini_api_key: str | None
    log_level: str


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _int_set(env: Mapping[str, str], name: str) -> frozenset[int]:
    raw = env.get(name, "")
    result: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            raise ConfigurationError(
                f"{name}: «{part}» не является числовым Telegram ID."
            ) from None
    return frozenset(result)


def load_settings(env: Mapping[str, str] | None = None, *, require_bot: bool = True) -> Settings:
    env = os.environ if env is None else env
    settings = Settings(
        bot_token=_optional(env, "BOT_TOKEN"),
        admin_ids=_int_set(env, "ADMIN_TELEGRAM_IDS"),
        allowed_chat_ids=_int_set(env, "ALLOWED_CHAT_IDS"),
        firebase_project_id=_optional(env, "FIREBASE_PROJECT_ID"),
        firebase_credentials_path=_optional(env, "FIREBASE_CREDENTIALS"),
        firebase_credentials_json=_optional(env, "FIREBASE_CREDENTIALS_JSON"),
        firebase_storage_bucket=_optional(env, "FIREBASE_STORAGE_BUCKET"),
        gemini_api_key=_optional(env, "GEMINI_API_KEY"),
        log_level=(_optional(env, "LOG_LEVEL") or "INFO").upper(),
    )
    if require_bot:
        if not settings.bot_token:
            raise ConfigurationError("Не задан BOT_TOKEN (токен от @BotFather).")
        if not settings.admin_ids:
            raise ConfigurationError(
                "Не задан ADMIN_TELEGRAM_IDS. Узнать свой ID можно командой /whoami у бота."
            )
    return settings
