"""Server-side validation of Telegram Mini App `initData`.

The Mini App sends `Telegram.WebApp.initData` (the raw query string) with
every request. It is trusted only after its signature checks out:

    secret_key = HMAC_SHA256(key="WebAppData", message=bot_token)
    hash       = hex(HMAC_SHA256(key=secret_key, message=data_check_string))

where `data_check_string` is every received field except `hash`, sorted by
key, as `key=value` lines joined with "\\n". `initDataUnsafe` is never used
for authorisation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode


class InitDataError(Exception):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 24 * 3600,
    now: float | None = None,
) -> TelegramUser:
    if not init_data or not bot_token:
        raise InitDataError("missing init data")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise InitDataError("malformed init data") from None
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("duplicate keys")
    received = fields.get("hash")
    if not received:
        raise InitDataError("no hash")

    expected = hmac.new(
        _secret_key(bot_token), _data_check_string(fields).encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("bad signature")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise InitDataError("no auth_date") from None
    current = time.time() if now is None else now
    if current - auth_date > max_age_seconds:
        raise InitDataError("init data expired")
    if auth_date - current > 300:
        raise InitDataError("auth_date in the future")

    try:
        user = json.loads(fields["user"])
        return TelegramUser(
            id=int(user["id"]),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            username=user.get("username"),
            language_code=user.get("language_code"),
            photo_url=user.get("photo_url"),
        )
    except (KeyError, ValueError, TypeError):
        raise InitDataError("no user") from None


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a signed initData string (tests, local demo). Not used for auth."""
    unsigned = {key: value for key, value in fields.items() if key != "hash"}
    signature = hmac.new(
        _secret_key(bot_token), _data_check_string(unsigned).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode({**unsigned, "hash": signature})


def make_init_data(user_id: int, bot_token: str, first_name: str = "Test", **extra: str) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": first_name}, separators=(",", ":")),
        **extra,
    }
    return sign_init_data(fields, bot_token)
