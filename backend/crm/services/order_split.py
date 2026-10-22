"""How many orders one photo becomes (the owner's rules, 04.10.2026).

* "3ta" / "3 ta" (also Cyrillic "та") in the caption means "3 pieces": three
  identical orders.
* Several links in the caption mean several products in one photo (e.g. a
  jacket and trousers on a model): one order per link, each with its own size
  when the caption makes it clear (a size on the link's line, or exactly as
  many sizes as links, in the same order). Brand and model stay empty: the
  photo shows several things, the admin fills them from the link («Из ссылки»).

Pure functions: no Telegram, no storage.
"""

import re
from dataclasses import dataclass

from crm.services.recognition import _SIZE_RE, _URL_RE, Recognition, extract_urls

MAX_ITEMS = 10
_QUANTITY_RE = re.compile(r"(?<![\w.,])(\d{1,2})\s*(?:ta|та)(?![\w])", re.IGNORECASE)


@dataclass(frozen=True)
class PlannedItem:
    brand: str | None
    model: str | None
    size: str | None
    link: str | None


def quantity(caption: str | None) -> int:
    """ "3ta" → 3; no marker (or a nonsense number) → 1."""
    match = _QUANTITY_RE.search(caption or "")
    if not match:
        return 1
    return max(1, min(int(match.group(1)), MAX_ITEMS))


def strip_quantity(caption: str | None) -> str | None:
    """The caption without "3ta", so the "3" is never read as a size."""
    if caption is None:
        return None
    return " ".join(_QUANTITY_RE.sub(" ", caption).split(" ")).strip() or None


def _sizes(text: str) -> list[str]:
    """All sizes in order, repeats kept (two items may both be "M")."""
    clean = _QUANTITY_RE.sub(" ", _URL_RE.sub(" ", text))
    return [" ".join(m.split()) for m in _SIZE_RE.findall(clean)]


def _link_sizes(caption: str, links: list[str]) -> list[str | None]:
    lines = caption.splitlines()
    per_line: list[str | None] = []
    for link in links:
        line = next((ln for ln in lines if link in ln), "")
        if sum(other in line for other in links) > 1:
            per_line.append(None)  # several links on one line: sizes are not per line
            continue
        found = _sizes(line)
        per_line.append(found[0] if len(found) == 1 else None)
    if all(per_line):
        return per_line
    overall = _sizes(caption)
    if len(overall) == len(links):
        return [s or overall[i] for i, s in enumerate(per_line)]
    return per_line


def plan(caption: str | None, recognition: Recognition) -> list[PlannedItem]:
    """The orders to create for one photo; the first one is the main order."""
    links = extract_urls(caption)
    if len(links) >= 2:
        links = links[:MAX_ITEMS]
        sizes = _link_sizes(caption or "", links)
        return [
            PlannedItem(None, None, size, link) for link, size in zip(links, sizes, strict=True)
        ]
    main = PlannedItem(recognition.brand, recognition.model, recognition.size, recognition.link)
    return [main] * quantity(caption)
