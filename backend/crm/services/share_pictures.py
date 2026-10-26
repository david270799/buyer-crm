"""The «Поделиться» pictures drawn on the server, for the bot (the owner, 26.10.2026).

The client's buttons «💰 Баланс» and «📦 Получил посылку» send the same pictures
the Mini App makes for «Поделиться» (web/src/lib/shareCard.ts): the balance with
the operations since the last top-up, and a shipment with its box photo and the
orders inside. Same layout and colours; Pillow instead of a browser canvas.
Nothing admin-only is drawn: no purchase prices, profit or shop links.
"""

import io
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from crm.domain.models import Order, Shipment
from crm.domain.money import format_krw, format_usd
from crm.domain.size_label import size_text
from crm.domain.timeutil import to_local

W = 1080
PAD = 48
INK = (17, 24, 39)
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
TILE_BG = (243, 244, 246)
NAVY = (31, 42, 58)
NAVY_TEXT = (185, 197, 214)
GREEN = (46, 106, 78)
RED_SOFT = (255, 180, 166)

ReadImage = Callable[[str], bytes | None]

# DejaVu (fonts-dejavu-core in the Docker image): Cyrillic and the ₩ sign.
_FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")
_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
           "сентября", "октября", "ноября", "декабря")  # fmt: skip


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for folder in _FONT_DIRS:
        path = Path(folder) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def long_date(value: datetime | None) -> str:
    if value is None:
        return ""
    local = to_local(value)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"


def goods_word(n: int) -> str:
    d, h = n % 10, n % 100
    if d == 1 and h != 11:
        return "товар"
    if 2 <= d <= 4 and not 12 <= h <= 14:
        return "товара"
    return "товаров"


def _width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> float:
    return draw.textlength(text, font=font)


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: float) -> str:
    if _width(draw, text, font) <= max_width:
        return text
    cut = text
    while len(cut) > 1 and _width(draw, f"{cut}…", font) > max_width:
        cut = cut[:-1]
    return f"{cut.rstrip()}…"


def _load(read: ReadImage, url: str | None) -> Image.Image | None:
    if not url:
        return None
    try:
        data = read(url)
        return Image.open(io.BytesIO(data)).convert("RGB") if data else None
    except Exception:  # noqa: BLE001 - a missing photo leaves an empty tile
        return None


def _paste(
    canvas: Image.Image, img: Image.Image, box: tuple[int, int, int, int], mode: str, radius: int
) -> None:
    """`img` inside the box: "cover" crops to fill, "contain" fits whole; rounded corners."""
    x, y, w, h = box
    scale = (
        max(w / img.width, h / img.height)
        if mode == "cover"
        else min(w / img.width, h / img.height)
    )
    dw, dh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    resized = img.resize((dw, dh), Image.LANCZOS)
    layer = Image.new("RGB", (w, h), TILE_BG if mode == "contain" else (255, 255, 255))
    layer.paste(resized, ((w - dw) // 2, (h - dh) // 2))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    canvas.paste(layer, (x, y), mask)


def _png(canvas: Image.Image) -> bytes:
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def shipment_picture(shipment: Shipment, orders: Sequence[Order], read: ReadImage) -> bytes:
    """«Отправка KR…», date and count, the box photo, then the orders three in a row."""
    cols, gap = 3, 24
    tile = (W - 2 * PAD - (cols - 1) * gap) // cols
    row_h = tile + 112
    box_url = shipment.photos[0]["photo_url"] if shipment.photos else shipment.photo_url
    box = _load(read, box_url)
    box_h = 560 if box else 0
    rows = (len(orders) + cols - 1) // cols
    height = PAD + 170 + box_h + rows * row_h + PAD - 24
    canvas = Image.new("RGB", (W, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    y = PAD
    title = _font(56, bold=True)
    draw.text((PAD, y), "Отправка", font=title, fill=INK)
    if shipment.tracking_code:
        x = PAD + _width(draw, "Отправка", title) + 22
        code = _font(46, bold=True)
        draw.text(
            (x, y + 8),
            _ellipsis(draw, shipment.tracking_code, code, W - PAD - x),
            font=code,
            fill=INK,
        )
    when = long_date(shipment.shipment_date or shipment.created_at)
    line = " · ".join(p for p in (when, f"{len(orders)} {goods_word(len(orders))}") if p)
    draw.text((PAD, y + 84), line, font=_font(36), fill=MUTED)
    y += 170

    if box:
        _paste(canvas, box, (PAD, y, W - 2 * PAD, 520), "cover", 28)
        y += box_h

    bold, small = _font(32, bold=True), _font(26)
    for i, order in enumerate(orders):
        x = PAD + (i % cols) * (tile + gap)
        top = y + (i // cols) * row_h
        draw.rounded_rectangle((x, top, x + tile, top + tile), radius=20, fill=TILE_BG)
        photo = _load(read, order.thumbnail_url or order.photo_url)
        if photo:
            _paste(canvas, photo, (x + 8, top + 8, tile - 16, tile - 16), "contain", 14)
        draw.rounded_rectangle((x, top, x + tile, top + tile), radius=20, outline=LINE, width=2)
        label = " · ".join(p for p in (order.id, size_text(order.size, order.size_kr)) if p)
        draw.text((x, top + tile + 14), _ellipsis(draw, label, bold, tile), font=bold, fill=INK)
        name = " ".join(p for p in (order.brand, order.model) if p)
        if name:
            draw.text(
                (x, top + tile + 58), _ellipsis(draw, name, small, tile), font=small, fill=MUTED
            )
    return _png(canvas)


def since_last_deposit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The operations since the last top-up (the top-up included), newest first."""
    for index, row in enumerate(rows):
        if row.get("type") == "deposit":
            return rows[: index + 1]
    return rows


def _entry_text(row: dict[str, Any]) -> str:
    kind = row.get("type")
    if kind in ("shipping_charge", "watch_charge"):
        code = (row.get("shipment") or {}).get("tracking_code") or row.get("shipment_id")
        head = "Доставка часов" if kind == "watch_charge" else "Доставка"
        return " · ".join(p for p in (head, code) if p)
    if row.get("order_id"):
        prefix = {"order_refund": "Возврат", "order_rebuy": "Перезаказ"}.get(kind or "")
        if kind == "order_discount":
            prefix = row.get("comment") or "Скидка"
        title = (row.get("order") or {}).get("title")
        return " · ".join(p for p in (prefix, row["order_id"], title) if p)
    if kind == "deposit":
        return "Пополнение"
    if kind == "adjustment":
        return f"Корректировка · {row['comment']}" if row.get("comment") else "Корректировка"
    return row.get("comment") or "Операция"


def balance_picture(
    balance_krw: int,
    krw_per_usd: Decimal | None,
    balance_usd: Decimal | None,
    rows: list[dict[str, Any]],
    read: ReadImage,
    today: datetime,
) -> bytes:
    """A navy card with the balance and the date, then the operations."""
    row_h = 124
    canvas = Image.new("RGB", (W, PAD + 310 + 60 + len(rows) * row_h + PAD), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    y = PAD
    draw.rounded_rectangle((PAD, y, W - PAD, y + 270), radius=32, fill=NAVY)
    draw.text((PAD + 40, y + 34), f"Баланс · {long_date(today)}", font=_font(32), fill=NAVY_TEXT)
    amount = format_krw(balance_krw)
    draw.text(
        (PAD + 40, y + 88),
        amount,
        font=_font(84, bold=True),
        fill=RED_SOFT if balance_krw < 0 else (255, 255, 255),
    )
    rate = f" · 1 $ = {int(krw_per_usd):,} ₩" if krw_per_usd else ""
    usd_line = f"{format_usd(balance_usd)}{rate}" if balance_usd is not None else rate[3:]
    draw.text((PAD + 40, y + 200), usd_line, font=_font(34), fill=NAVY_TEXT)
    y += 310

    heading = "Операции с последнего пополнения" if rows else "Операций пока нет"
    draw.text((PAD, y), heading, font=_font(34, bold=True), fill=INK)
    y += 60

    text_font, date_font, money_font = _font(32), _font(26), _font(34, bold=True)
    for row in rows:
        draw.rounded_rectangle((PAD, y + 12, PAD + 84, y + 96), radius=16, fill=TILE_BG)
        order = row.get("order") or {}
        shipment = row.get("shipment") or {}
        thumb_url = order.get("thumbnail_url") or (
            None if row.get("type") == "watch_charge" else shipment.get("thumbnail_url")
        )
        thumb = _load(read, thumb_url)
        if thumb:
            _paste(canvas, thumb, (PAD, y + 12, 84, 84), "cover", 16)
        value = int(row.get("amount_krw") or 0)
        money = f"{'+' if value > 0 else '−'} {format_krw(abs(value))}"
        money_w = _width(draw, money, money_font)
        draw.text(
            (W - PAD - money_w, y + 38), money, font=money_font, fill=GREEN if value > 0 else INK
        )
        text_x = PAD + 108
        text_max = W - PAD - money_w - 24 - text_x
        draw.text(
            (text_x, y + 18),
            _ellipsis(draw, _entry_text(row), text_font, text_max),
            font=text_font,
            fill=INK,
        )
        created = row.get("created_at")
        draw.text(
            (text_x, y + 62),
            long_date(created if isinstance(created, datetime) else None),
            font=date_font,
            fill=MUTED,
        )
        y += row_h
        draw.rectangle((PAD, y - 4, W - PAD, y - 2), fill=(238, 240, 243))
    return _png(canvas)
