"""Pictures for «Витрина» from a shop screenshot (the owner, 01.11.2026).

`for_gemini` makes a plain JPEG of the whole screenshot (not squared: Gemini's
photo box must match the picture it saw); `crop` cuts the product photo out
of the original by that box when no page with real photos was found.
"""

import io
import re

from PIL import Image, ImageOps

from crm.domain.errors import ValidationError

MAX_SIDE = 1600
_MAX_INPUT_PIXELS = 50_000_000


def _open(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > _MAX_INPUT_PIXELS:
            raise ValidationError("Скриншот слишком большой.")
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")
    except ValidationError:
        raise
    except Exception:  # noqa: BLE001 - not a picture
        raise ValidationError("Не удалось открыть скриншот.") from None


def _jpeg(image: Image.Image, quality: int = 88) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def for_gemini(data: bytes) -> bytes:
    image = _open(data)
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return _jpeg(image)


def crop(data: bytes, box: list[int]) -> bytes | None:
    """The part of the screenshot inside [ymin, xmin, ymax, xmax] (0…1000);
    None when the box is too small to be a product photo."""
    image = _open(data)
    ymin, xmin, ymax, xmax = box
    left, right = image.width * xmin // 1000, image.width * xmax // 1000
    top, bottom = image.height * ymin // 1000, image.height * ymax // 1000
    if right - left < 120 or bottom - top < 120:
        return None
    return _jpeg(image.crop((left, top, right, bottom)), 92)


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def page_has_code(html: str, code: str | None) -> bool:
    """The page is about this very product: its style code is on it («NJ3BS51A»,
    also written «NJ3BS51A-BLK» or «nj3bs51a»)."""
    token = _squash(code or "")
    return len(token) >= 5 and token in _squash(html)
