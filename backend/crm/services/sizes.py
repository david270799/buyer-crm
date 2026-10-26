"""The usual size and the Korean size from one caption (the owner, 16.10.2026).

Clients write «L 80», «42/265», «M-95» or just «270». The usual size goes to
`size`, the Korean one to `size_kr`:

* usual: letters (XS … 3XL), shoes EU 33–48, US/UK 1–15, «EU 42», «US 9»;
* Korean: clothes 75–120 (75, 80, 85 … 110), shoes 210–310 (220, 225 … 300), «KR 265»;
  shoes in centimetres 20–29.5 (28, 25.5 — owner, 26.10.2026) are stored in millimetres
  (280, 255) like every Korean shoe size; «075» is stored as «75». For clothes the
  same numbers are a waist in inches (jeans W28) and stay the usual size.
"""

import re

from crm.services.recognition import find_sizes

_LETTERS = re.compile(r"^(?:XXS|XS|S|M|L|XL|XXL|XXXL|[2-5]XL)$", re.IGNORECASE)
_PREFIXED = re.compile(r"^(EU|US|UK|JP|KR)\s?(\d{1,3}(?:[.,]5)?)$", re.IGNORECASE)


def kind(size: str, clothes: bool = False) -> str | None:
    """'usual', 'kr' or None (a number we cannot place)."""
    text = size.strip()
    if _LETTERS.match(text):
        return "usual"
    prefixed = _PREFIXED.match(text)
    if prefixed:
        return "kr" if prefixed.group(1).upper() == "KR" else "usual"
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    if 1 <= number <= 15 or 33 <= number <= 48 or (clothes and 20 <= number <= 32):
        return "usual"
    if 75 <= number <= 120 or 210 <= number <= 310 or 20 <= number < 30:
        return "kr"
    return None


def korean_value(size: str) -> str:
    """«KR 265» → «265», «28» / «25,5» (cm) → «280» / «255», «075» → «75»."""
    text = re.sub(r"^KR\s?", "", size.strip(), flags=re.IGNORECASE)
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return text
    if 20 <= number < 30:
        number *= 10
    return f"{number:g}"


def split_sizes(text: str | None, clothes: bool = False) -> tuple[str | None, str | None]:
    """(size, size_kr) when the text has at most one of each; unclear parts → None."""
    usual: list[str] = []
    korean: list[str] = []
    for size in find_sizes(text):
        found = kind(size, clothes)
        if found == "usual":
            usual.append(size.upper() if _LETTERS.match(size) else size)
        elif found == "kr":
            korean.append(korean_value(size))
    return (usual[0] if len(usual) == 1 else None, korean[0] if len(korean) == 1 else None)


def order_sizes(
    recognised: str | None, caption: str | None, *, from_caption: bool, clothes: bool = False
) -> tuple[str | None, str | None]:
    """Sizes for a new order: the caption wins when it names a size (and holds
    one product), else what Gemini read; a size we cannot place stays `size`."""
    if from_caption:
        caption_size, caption_kr = split_sizes(caption, clothes)
        if caption_size or caption_kr:
            return caption_size, caption_kr
    size, size_kr = split_sizes(recognised, clothes)
    if recognised and size is None and size_kr is None:
        return recognised, None
    return size, size_kr
