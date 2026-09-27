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
    gemini_model: str | None = None
    # Mini App / HTTP API
    mini_app_url: str | None = None
    web_origins: tuple[str, ...] = ()
    init_data_max_age_hours: int = 24
    port: int = 8080


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


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigurationError(f"{name} должен быть положительным целым числом.")
    return int(raw)


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
        gemini_model=_optional(env, "GEMINI_MODEL"),
        log_level=(_optional(env, "LOG_LEVEL") or "INFO").upper(),
        mini_app_url=_optional(env, "MINI_APP_URL"),
        web_origins=tuple(
            origin.strip().rstrip("/")
            for origin in env.get("WEB_ORIGINS", "").split(",")
            if origin.strip()
        ),
        init_data_max_age_hours=_positive_int(env, "INIT_DATA_MAX_AGE_HOURS", 24),
        port=_positive_int(env, "PORT", 8080),
    )
    if settings.mini_app_url and not settings.mini_app_url.startswith("https://"):
        raise ConfigurationError("MINI_APP_URL должен начинаться с https:// (требование Telegram).")
    # ADMIN_TELEGRAM_IDS may be empty on the very first start: the bot then gives
    # nobody access and answers /start and /whoami with the person's Telegram ID.
    if require_bot and not settings.bot_token:
        raise ConfigurationError("Не задан BOT_TOKEN (токен от @BotFather).")
    return settings
